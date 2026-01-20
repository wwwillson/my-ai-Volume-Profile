import streamlit as st
import yfinance as yf
import pandas as pd
import pandas_ta as ta
import plotly.graph_objects as go
import numpy as np

# --- 頁面設定 ---
st.set_page_config(page_title="BTC Volume Profile Trading Bot", layout="wide")

# --- 側邊欄設定 ---
st.sidebar.title("交易參數設定")
ticker = st.sidebar.text_input("交易對 Symbol", "BTC-USD")
interval = st.sidebar.selectbox("K線週期", ["15m", "30m", "1h", "4h", "1d"], index=2)
lookback_period = st.sidebar.slider("Volume Profile 計算範圍 (K線數量)", 50, 500, 200)
va_percent = st.sidebar.slider("Value Area 百分比 (預設0.7)", 0.1, 1.0, 0.7)
risk_reward_ratio = st.sidebar.number_input("盈虧比 (R:R)", value=2.0)

# --- 交易邏輯說明 ---
with st.expander("📊 交易策略邏輯 (基於 Market Profile/Volume Profile)", expanded=True):
    st.markdown("""
    ### 策略原理：
    此程式參考影片中的 **Volume Profile (成交量分佈)** 概念。
    市場大部分時間會在 **Value Area (價值區域)** 內震盪，當價格觸碰邊界並發生反轉時，視為交易機會。

    #### 關鍵指標：
    1.  **POC (紅色線)**: 控制點，成交量最大的價格水平。
    2.  **VAH (綠色線)**: 價值區域高點 (Value Area High)。
    3.  **VAL (綠色線)**: 價值區域低點 (Value Area Low)。

    #### 進場規則 (均值回歸)：
    - **多單 (Long)**: 當價格觸及或跌破 **VAL**，但收盤價站回 VAL 之上（假跌破/支撐確認）。
    - **空單 (Short)**: 當價格觸及或突破 **VAH**，但收盤價跌回 VAH 之下（假突破/壓力確認）。

    #### 出場規則：
    - **止損 (Stop Loss)**: 設定在最近的 Swing Low/High 或 VAH/VAL 外側。
    - **止盈 (Take Profit)**: 目標設為 POC 或對側邊界，並依據設定的盈虧比動態調整。
    """)

# --- 核心函數：計算 Volume Profile ---
def calculate_volume_profile(df, lookback, va_pct):
    # 取最近 lookback 根 K 線
    subset = df.tail(lookback).copy()
    
    # 定義價格區間 (Bin size)
    price_min = subset['Low'].min()
    price_max = subset['High'].max()
    price_step = (price_max - price_min) / 100  # 分成 100 個區間
    
    # 初始化 Volume Profile 字典
    vp = {}
    
    for i, row in subset.iterrows():
        # 簡單估算：將該根 K 線的量平均分配到 High 到 Low 的價格區間
        # 更精確的做法是 Tick data，但這裡用 K 線模擬
        levels = np.arange(row['Low'], row['High'], price_step)
        if len(levels) == 0: continue
        vol_per_level = row['Volume'] / len(levels)
        
        for level in levels:
            level_rounded = round(level / price_step) * price_step
            vp[level_rounded] = vp.get(level_rounded, 0) + vol_per_level
            
    # 轉為 DataFrame
    vp_df = pd.DataFrame(list(vp.items()), columns=['Price', 'Volume'])
    vp_df = vp_df.sort_values(by='Price')
    
    # 計算 POC
    max_vol_idx = vp_df['Volume'].idxmax()
    poc_price = vp_df.loc[max_vol_idx, 'Price']
    
    # 計算 Value Area (VA)
    total_volume = vp_df['Volume'].sum()
    target_volume = total_volume * va_pct
    
    # 從 POC 開始向外擴展尋找 VA
    current_idx = max_vol_idx
    current_volume = vp_df.loc[current_idx, 'Volume']
    left = current_idx - 1
    right = current_idx + 1
    
    while current_volume < target_volume:
        vol_left = vp_df.loc[left, 'Volume'] if left >= 0 else 0
        vol_right = vp_df.loc[right, 'Volume'] if right < len(vp_df) else 0
        
        if vol_left > vol_right:
            current_volume += vol_left
            left -= 1
        else:
            current_volume += vol_right
            right += 1
            
        if left < 0 and right >= len(vp_df):
            break
            
    val_price = vp_df.loc[left + 1, 'Price']
    vah_price = vp_df.loc[right - 1, 'Price']
    
    return vp_df, poc_price, vah_price, val_price

# --- 獲取數據 ---
@st.cache_data(ttl=60)
def get_data(ticker, interval, period="1mo"):
    try:
        df = yf.download(ticker, interval=interval, period=period, progress=False)
        df.columns = df.columns.droplevel(1) if isinstance(df.columns, pd.MultiIndex) else df.columns
        return df
    except Exception as e:
        st.error(f"數據獲取失敗: {e}")
        return pd.DataFrame()

# --- 主程式邏輯 ---
df = get_data(ticker, interval)

if not df.empty:
    # 計算 Volume Profile
    vp_df, poc, vah, val = calculate_volume_profile(df, lookback_period, va_percent)
    
    # 獲取最新價格數據
    last_close = df['Close'].iloc[-1]
    last_high = df['High'].iloc[-1]
    last_low = df['Low'].iloc[-1]
    prev_close = df['Close'].iloc[-2]
    
    # --- 訊號檢測 ---
    signal = "None"
    signal_color = "gray"
    stop_loss = 0.0
    take_profit = 0.0
    
    # 多單邏輯：價格跌破 VAL 後收回
    if df['Low'].iloc[-1] < val and df['Close'].iloc[-1] > val:
        signal = "BUY (Long)"
        signal_color = "green"
        stop_loss = df['Low'].iloc[-1] * 0.995 # 止損放在當前低點下方一點
        distance = last_close - stop_loss
        take_profit = last_close + (distance * risk_reward_ratio)

    # 空單邏輯：價格突破 VAH 後跌回
    elif df['High'].iloc[-1] > vah and df['Close'].iloc[-1] < vah:
        signal = "SELL (Short)"
        signal_color = "red"
        stop_loss = df['High'].iloc[-1] * 1.005 # 止損放在當前高點上方一點
        distance = stop_loss - last_close
        take_profit = last_close - (distance * risk_reward_ratio)

    # --- 顯示主要指標 ---
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("當前價格", f"{last_close:.2f}")
    col2.metric("VAH (壓力)", f"{vah:.2f}")
    col3.metric("VAL (支撐)", f"{val:.2f}")
    col4.metric("POC (控制點)", f"{poc:.2f}")

    # --- 訊號提示區 ---
    if signal != "None":
        st.success(f"🚨 **交易訊號觸發: {signal}**")
        col_s1, col_s2, col_s3 = st.columns(3)
        col_s1.info(f"建議進場: {last_close:.2f}")
        col_s2.error(f"建議止損 (SL): {stop_loss:.2f}")
        col_s3.success(f"建議止盈 (TP): {take_profit:.2f}")
    else:
        st.info("目前無明確進場訊號 (價格未在 VAH/VAL 邊緣發生反轉)")

    # --- 繪製圖表 (Plotly) ---
    fig = go.Figure()

    # 1. K線圖
    fig.add_trace(go.Candlestick(
        x=df.index,
        open=df['Open'], high=df['High'],
        low=df['Low'], close=df['Close'],
        name='K線'
    ))

    # 2. 繪製 VAH, VAL, POC 線
    fig.add_hline(y=vah, line_dash="dash", line_color="rgba(0, 255, 0, 0.7)", annotation_text="VAH")
    fig.add_hline(y=val, line_dash="dash", line_color="rgba(0, 255, 0, 0.7)", annotation_text="VAL")
    fig.add_hline(y=poc, line_color="rgba(255, 0, 0, 0.8)", annotation_text="POC")

    # 3. 繪製 Volume Profile (右側直方圖)
    # 為了不遮擋K線，我們將 Profile 畫在右側，或者使用較淡的顏色疊加
    # 這裡示範簡單的水平 Bar
    max_vol = vp_df['Volume'].max()
    # 縮放 Volume 以適應時間軸 (簡單視覺化處理)
    scale_factor = (df.index[-1] - df.index[0]).total_seconds() * 1000 / max_vol * 0.2
    
    # 標記止損止盈 (如果有訊號)
    if signal != "None":
        # 止損線
        fig.add_shape(type="line",
            x0=df.index[-5], y0=stop_loss, x1=df.index[-1], y1=stop_loss,
            line=dict(color="red", width=2), name="SL"
        )
        fig.add_annotation(x=df.index[-1], y=stop_loss, text="SL", showarrow=True, arrowhead=1)
        
        # 止盈線
        fig.add_shape(type="line",
            x0=df.index[-5], y0=take_profit, x1=df.index[-1], y1=take_profit,
            line=dict(color="green", width=2), name="TP"
        )
        fig.add_annotation(x=df.index[-1], y=take_profit, text="TP", showarrow=True, arrowhead=1)
        
        # 進場標記
        fig.add_annotation(
            x=df.index[-1], y=last_close,
            text=signal,
            showarrow=True,
            arrowhead=2,
            arrowsize=1,
            arrowwidth=2,
            arrowcolor=signal_color
        )

    # 圖表佈局設定
    fig.update_layout(
        title=f"{ticker} Volume Profile Analysis",
        yaxis_title="Price",
        xaxis_title="Time",
        height=600,
        template="plotly_dark",
        showlegend=True
    )

    st.plotly_chart(fig, use_container_width=True)
    
    st.markdown("---")
    st.caption("免責聲明：此程式僅供技術分析教育用途，不構成投資建議。加密貨幣市場波動劇烈，請自行承擔風險。")

else:
    st.warning("等待數據加載或數據為空...")
