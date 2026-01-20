import streamlit as st
import ccxt
import pandas as pd
import pandas_ta as ta
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import numpy as np
from datetime import datetime

# --- 頁面設定 (開啟寬螢幕模式) ---
st.set_page_config(page_title="BTC Pro Trading Tool", layout="wide")

# --- CSS 優化 (讓圖表佔滿寬度) ---
st.markdown("""
<style>
    .block-container {padding-top: 1rem; padding-bottom: 0rem; padding-left: 1rem; padding-right: 1rem;}
</style>
""", unsafe_allow_html=True)

# --- 側邊欄設定 ---
with st.sidebar:
    st.title("⚙️ 參數設定")
    symbol = st.text_input("交易對 (Binance)", "BTC/USDT")
    timeframe = st.selectbox("時間週期", ["15m", "1h", "4h", "1d"], index=1)
    limit = st.slider("K線數量 (影響計算範圍)", 100, 1000, 500)
    
    st.markdown("---")
    st.markdown("### 策略參數")
    va_percent = st.slider("Value Area %", 0.1, 0.9, 0.7)
    risk_reward = st.number_input("盈虧比 (Risk:Reward)", value=2.0, step=0.1)
    
    if st.button("🔄 刷新數據", type="primary"):
        st.cache_data.clear()

# --- 核心函數：從 Binance 獲取數據 (使用 CCXT，速度快且穩定) ---
@st.cache_data(ttl=15)  # 15秒緩存，避免過度請求
def fetch_binance_data(symbol, timeframe, limit):
    try:
        exchange = ccxt.binance()
        # 獲取 OHLCV
        bars = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        df = pd.DataFrame(bars, columns=['timestamp', 'Open', 'High', 'Low', 'Close', 'Volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        return df
    except Exception as e:
        st.error(f"數據獲取失敗 (請檢查交易對名稱): {e}")
        return pd.DataFrame()

# --- 核心函數：計算 Volume Profile (使用 Numpy 加速) ---
def calculate_vp_numpy(df, va_pct=0.7, n_bins=100):
    # 定義價格區間
    price_min = df['Low'].min()
    price_max = df['High'].max()
    
    # 建立價格區間 (Bins)
    bins = np.linspace(price_min, price_max, n_bins)
    
    # 計算每個區間的成交量 (這裡簡化使用 Close 對應的 Volume)
    # 專業版可用 Tick 數據，但在 K 線層級此方法足夠
    hist, bin_edges = np.histogram(df['Close'], bins=bins, weights=df['Volume'])
    
    # 建立 DataFrame
    vp_df = pd.DataFrame({'Volume': hist, 'Price': bin_edges[:-1]})
    
    # 1. 找出 POC (最大量價格)
    max_vol_idx = vp_df['Volume'].idxmax()
    poc_price = vp_df.loc[max_vol_idx, 'Price']
    
    # 2. 計算 Value Area (VA)
    total_vol = vp_df['Volume'].sum()
    target_vol = total_vol * va_pct
    
    # 從 POC 向外擴散累加成交量
    current_vol = vp_df.loc[max_vol_idx, 'Volume']
    up_idx = max_vol_idx
    down_idx = max_vol_idx
    
    while current_vol < target_vol:
        up_vol = vp_df.loc[up_idx + 1, 'Volume'] if up_idx + 1 < len(vp_df) else 0
        down_vol = vp_df.loc[down_idx - 1, 'Volume'] if down_idx - 1 >= 0 else 0
        
        if up_vol > down_vol:
            current_vol += up_vol
            up_idx += 1
        else:
            current_vol += down_vol
            down_idx -= 1
            
        if up_idx >= len(vp_df) -1 and down_idx <= 0:
            break
            
    vah = vp_df.loc[up_idx, 'Price']
    val = vp_df.loc[down_idx, 'Price']
    
    return vp_df, poc_price, vah, val

# --- 主程式 ---
df = fetch_binance_data(symbol, timeframe, limit)

if not df.empty:
    # 計算 VP
    vp_df, poc, vah, val = calculate_vp_numpy(df, va_percent)
    
    # 最新數據
    last_close = df['Close'].iloc[-1]
    last_low = df['Low'].iloc[-1]
    last_high = df['High'].iloc[-1]
    
    # --- 交易訊號判斷 ---
    signal_txt = "無訊號"
    signal_color = "grey"
    sl_price = 0.0
    tp_price = 0.0
    
    # 判斷邏輯：價格曾在 VAL 之下，但收盤收回 VAL 之上 (假跌破)
    if df['Low'].iloc[-1] < val and df['Close'].iloc[-1] > val:
        signal_txt = "LONG (做多)"
        signal_color = "#00FF00" # 亮綠
        sl_price = df['Low'].iloc[-1]  # 止損設在當前K線最低點
        risk = last_close - sl_price
        tp_price = last_close + (risk * risk_reward)
        
    # 判斷邏輯：價格曾在 VAH 之上，但收盤跌回 VAH 之下 (假突破)
    elif df['High'].iloc[-1] > vah and df['Close'].iloc[-1] < vah:
        signal_txt = "SHORT (做空)"
        signal_color = "#FF0000" # 亮紅
        sl_price = df['High'].iloc[-1] # 止損設在當前K線最高點
        risk = sl_price - last_close
        tp_price = last_close - (risk * risk_reward)

    # --- 介面佈局 ---
    
    # 頂部資訊欄
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("當前價格", f"{last_close:.2f}")
    c2.metric("VAH (壓力)", f"{vah:.2f}", delta_color="inverse")
    c3.metric("VAL (支撐)", f"{val:.2f}", delta_color="normal")
    c4.metric("POC (核心)", f"{poc:.2f}")
    
    if signal_txt != "無訊號":
        c5.markdown(f"### <span style='color:{signal_color}'>{signal_txt}</span>", unsafe_allow_html=True)
        st.toast(f"觸發交易訊號: {signal_txt}!", icon="🚨")
    else:
        c5.write("等待訊號...")

    # --- 繪圖 (使用 Subplots 將 K線 與 Volume Profile 分開) ---
    # 建立 1行2列 的圖表，共享Y軸 (價格軸)
    fig = make_subplots(
        rows=1, cols=2, 
        shared_yaxes=True, 
        column_widths=[0.75, 0.25], # 左邊佔75%，右邊佔25%
        horizontal_spacing=0.02,
        subplot_titles=(f"{symbol} K-Line Chart", "Volume Profile")
    )

    # 1. 左側：K線圖
    fig.add_trace(go.Candlestick(
        x=df.index,
        open=df['Open'], high=df['High'],
        low=df['Low'], close=df['Close'],
        name="Price"
    ), row=1, col=1)

    # 2. 左側：關鍵線位 (VAH, VAL, POC)
    # 使用 Shape 線條延伸到全圖
    fig.add_hline(y=vah, line_dash="dot", line_color="green", line_width=1, row=1, col=1, annotation_text="VAH")
    fig.add_hline(y=val, line_dash="dot", line_color="green", line_width=1, row=1, col=1, annotation_text="VAL")
    fig.add_hline(y=poc, line_color="red", line_width=2, row=1, col=1, annotation_text="POC")

    # 3. 標記止盈止損 (如果有訊號)
    if signal_txt != "無訊號":
        # 標記進場點
        fig.add_trace(go.Scatter(
            x=[df.index[-1]], y=[last_close],
            mode='markers', marker=dict(color=signal_color, size=15, symbol='cross'),
            name="Entry"
        ), row=1, col=1)
        
        # 繪製 SL/TP 區間框
        if signal_txt == "LONG (做多)":
            fill_color = "rgba(0, 255, 0, 0.1)"
            line_color = "green"
        else:
            fill_color = "rgba(255, 0, 0, 0.1)"
            line_color = "red"
            
        # 止盈線
        fig.add_hline(y=tp_price, line_color=line_color, line_dash="dash", annotation_text=f"TP: {tp_price:.2f}", row=1, col=1)
        # 止損線
        fig.add_hline(y=sl_price, line_color="white", line_dash="dash", annotation_text=f"SL: {sl_price:.2f}", row=1, col=1)

    # 4. 右側：Volume Profile (水平直方圖)
    # 區分顏色：POC用紅色，VA內用藍色，VA外用灰色
    colors = []
    for price in vp_df['Price']:
        if abs(price - poc) < (poc * 0.001): # 接近 POC
            colors.append('red')
        elif val <= price <= vah: # 在 Value Area 內
            colors.append('rgba(0, 100, 255, 0.5)')
        else: # 在 Value Area 外
            colors.append('rgba(128, 128, 128, 0.2)')

    fig.add_trace(go.Bar(
        x=vp_df['Volume'],
        y=vp_df['Price'],
        orientation='h',
        marker_color=colors,
        name="Volume Profile",
        showlegend=False
    ), row=1, col=2)

    # --- 圖表樣式設定 ---
    fig.update_layout(
        height=800, # 增加高度，解決 "圖太小" 問題
        template="plotly_dark",
        dragmode="pan",
        xaxis_rangeslider_visible=False, # 隱藏下方滑桿以節省空間
        margin=dict(l=10, r=10, t=30, b=10),
        hovermode="y unified" # 讓滑鼠懸停時更容易對齊價格
    )
    
    # 鎖定右側 Volume Profile 的顯示方式
    fig.update_xaxes(title_text="Volume", row=1, col=2, showgrid=False)
    fig.update_yaxes(showgrid=True, gridcolor='rgba(128,128,128,0.2)')

    st.plotly_chart(fig, use_container_width=True)

    # --- 下方數據表格 ---
    with st.expander("📊 查看詳細數據"):
        st.dataframe(df.tail(10).sort_index(ascending=False))

else:
    st.warning("無法獲取數據，請檢查網路連線或稍後再試。")
