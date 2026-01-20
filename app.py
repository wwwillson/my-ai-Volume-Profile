import streamlit as st
import ccxt
import pandas as pd
import pandas_ta as ta
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import numpy as np
from datetime import datetime

# --- 1. 頁面設定 ---
st.set_page_config(page_title="BTC VP Trading Bot", layout="wide")

# CSS 優化：減少頂部留白
st.markdown("""
<style>
    .block-container {padding-top: 1rem; padding-bottom: 0rem;}
</style>
""", unsafe_allow_html=True)

# --- 2. 側邊欄設定 ---
with st.sidebar:
    st.title("⚙️ 參數設定")
    # 改用 Kraken 的交易對格式
    symbol = st.text_input("交易對 (Kraken)", "BTC/USD") 
    timeframe = st.selectbox("時間週期", ["15m", "30m", "1h", "4h", "1d"], index=2)
    # 預設降低一點以加速啟動
    limit = st.slider("K線數量", 100, 1000, 300) 
    
    st.markdown("---")
    st.markdown("### 策略參數")
    va_percent = st.slider("Value Area %", 0.1, 0.9, 0.7)
    risk_reward = st.number_input("盈虧比 (R:R)", value=2.0, step=0.1)
    
    refresh = st.button("🔄 刷新數據", type="primary")
    if refresh:
        st.cache_data.clear()

# --- 3. 核心函數：獲取數據 (改用 Kraken) ---
@st.cache_data(ttl=30)
def fetch_data(symbol, timeframe, limit):
    # 使用 st.status 顯示進度，避免使用者以為卡死
    try:
        # 改用 Kraken，因為 Binance 會擋雲端伺服器 IP
        exchange = ccxt.kraken() 
        
        # 抓取數據
        bars = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        
        # 整理數據
        df = pd.DataFrame(bars, columns=['timestamp', 'Open', 'High', 'Low', 'Close', 'Volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        return df
    except Exception as e:
        return None

# --- 4. 核心函數：計算 Volume Profile ---
def calculate_vp(df, va_pct=0.7, n_bins=100):
    try:
        price_min = df['Low'].min()
        price_max = df['High'].max()
        
        # 建立價格區間
        bins = np.linspace(price_min, price_max, n_bins)
        
        # 計算分佈 (Numpy 加速)
        hist, bin_edges = np.histogram(df['Close'], bins=bins, weights=df['Volume'])
        vp_df = pd.DataFrame({'Volume': hist, 'Price': bin_edges[:-1]})
        
        # 找 POC
        max_idx = vp_df['Volume'].idxmax()
        poc = vp_df.loc[max_idx, 'Price']
        
        # 找 VA (Value Area)
        total_vol = vp_df['Volume'].sum()
        target_vol = total_vol * va_pct
        
        current_vol = vp_df.loc[max_idx, 'Volume']
        up = max_idx
        down = max_idx
        
        while current_vol < target_vol:
            v_up = vp_df.loc[up+1, 'Volume'] if up+1 < len(vp_df) else 0
            v_down = vp_df.loc[down-1, 'Volume'] if down-1 >= 0 else 0
            
            if v_up > v_down:
                current_vol += v_up
                up += 1
            else:
                current_vol += v_down
                down -= 1
            
            if up >= len(vp_df)-1 and down <= 0:
                break
                
        return vp_df, poc, vp_df.loc[up, 'Price'], vp_df.loc[down, 'Price']
    except Exception:
        return pd.DataFrame(), 0, 0, 0

# --- 5. 主程式邏輯 ---
with st.status("正在連線交易所...", expanded=True) as status:
    st.write("正在從 Kraken 下載數據...")
    df = fetch_data(symbol, timeframe, limit)
    
    if df is not None and not df.empty:
        st.write("正在計算 Volume Profile...")
        vp_df, poc, vah, val = calculate_vp(df, va_percent)
        status.update(label="數據載入完成!", state="complete", expanded=False)
    else:
        status.update(label="數據下載失敗", state="error")
        st.error("無法下載數據。可能原因：交易對名稱錯誤 (Kraken 使用 BTC/USD) 或網路連線問題。")
        st.stop()

# 最新價格數據
last_close = df['Close'].iloc[-1]
last_low = df['Low'].iloc[-1]
last_high = df['High'].iloc[-1]

# --- 6. 訊號邏輯 ---
signal = "WAIT"
color = "gray"
sl = 0.0
tp = 0.0

# 策略：價格跌破 VAL 收回 (做多)
if df['Low'].iloc[-1] < val and df['Close'].iloc[-1] > val:
    signal = "LONG"
    color = "#00FF00"
    sl = df['Low'].iloc[-1]
    risk = last_close - sl
    tp = last_close + (risk * risk_reward)

# 策略：價格突破 VAH 跌回 (做空)
elif df['High'].iloc[-1] > vah and df['Close'].iloc[-1] < vah:
    signal = "SHORT"
    color = "#FF0000"
    sl = df['High'].iloc[-1]
    risk = sl - last_close
    tp = last_close - (risk * risk_reward)

# --- 7. 畫面顯示 ---

# 頂部指標
m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("價格", f"{last_close:.0f}")
m2.metric("VAH", f"{vah:.0f}")
m3.metric("VAL", f"{val:.0f}")
m4.metric("POC", f"{poc:.0f}")
if signal != "WAIT":
    m5.markdown(f"### <span style='color:{color}'>{signal}</span>", unsafe_allow_html=True)
else:
    m5.write("等待訊號...")

# 繪圖 (左右分佈)
fig = make_subplots(
    rows=1, cols=2, 
    shared_yaxes=True, 
    column_widths=[0.8, 0.2], 
    horizontal_spacing=0.01
)

# K線
fig.add_trace(go.Candlestick(
    x=df.index, open=df['Open'], high=df['High'],
    low=df['Low'], close=df['Close'], name="BTC"
), row=1, col=1)

# 關鍵線位
fig.add_hline(y=vah, line_dash="dot", line_color="green", row=1, col=1)
fig.add_hline(y=val, line_dash="dot", line_color="green", row=1, col=1)
fig.add_hline(y=poc, line_color="red", line_width=2, row=1, col=1)

# 交易標記
if signal != "WAIT":
    # 進場點
    fig.add_trace(go.Scatter(
        x=[df.index[-1]], y=[last_close], mode='markers',
        marker=dict(color=color, size=12, symbol='x'), name="Signal"
    ), row=1, col=1)
    
    # 止盈止損線
    fig.add_hline(y=tp, line_color=color, line_dash="dash", annotation_text="TP", row=1, col=1)
    fig.add_hline(y=sl, line_color="white", line_dash="dash", annotation_text="SL", row=1, col=1)

# Volume Profile
colors = ['red' if abs(p - poc) < poc*0.001 else 'blue' if val <= p <= vah else 'gray' for p in vp_df['Price']]
fig.add_trace(go.Bar(
    x=vp_df['Volume'], y=vp_df['Price'], orientation='h',
    marker_color=colors, showlegend=False
), row=1, col=2)

fig.update_layout(
    height=700, 
    template="plotly_dark", 
    margin=dict(l=0, r=0, t=30, b=0),
    xaxis_rangeslider_visible=False,
    hovermode="y unified"
)
# 隱藏右側X軸刻度
fig.update_xaxes(showticklabels=False, row=1, col=2)

st.plotly_chart(fig, use_container_width=True)
