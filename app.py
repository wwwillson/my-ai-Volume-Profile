import streamlit as st
import ccxt
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import numpy as np
from streamlit_autorefresh import st_autorefresh

# --- 1. 頁面設定 ---
st.set_page_config(page_title="BTC Trading Bot", layout="wide")

# --- 2. 側邊欄 ---
with st.sidebar:
    st.title("⚙️ 參數設定")
    
    # 自動刷新
    if st.toggle("開啟 4 分鐘自動刷新"):
        count = st_autorefresh(interval=240000, key="refresh")
        st.write(f"刷新次數: {count}")

    symbol = st.text_input("交易對", "BTC/USDT")
    timeframe = st.selectbox("週期", ["5m", "15m", "1h", "4h", "1d"], index=0)
    limit = st.slider("K線數量", 100, 2000, 300)
    
    st.divider()
    va_percent = st.slider("Value Area %", 0.1, 0.9, 0.7)
    risk_reward = st.number_input("盈虧比", value=2.0)
    
    if st.button("🔄 刷新"):
        st.cache_data.clear()

    # 交易邏輯說明
    with st.expander("📖 交易邏輯", expanded=True):
        st.write("""
        **🟢 做多 (LONG):**
        跌破 VAL 後收回 -> 進場
        **🔴 做空 (SHORT):**
        突破 VAH 後跌回 -> 進場
        """)

# --- 3. 抓取數據 ---
@st.cache_data(ttl=15, show_spinner=False)
def get_data(symbol, timeframe, limit):
    try:
        exchange = ccxt.binance({'enableRateLimit': True, 'timeout': 10000})
        bars = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        df = pd.DataFrame(bars, columns=['timestamp', 'Open', 'High', 'Low', 'Close', 'Volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        return df
    except:
        return pd.DataFrame()

# --- 4. 計算 VP (防當機版) ---
def calculate_vp(df, va_pct):
    try:
        # 使用 Numpy 快速計算
        close = df['Close'].values
        vol = df['Volume'].values
        
        hist, bins = np.histogram(close, bins=120, weights=vol)
        
        max_idx = hist.argmax()
        poc = bins[max_idx]
        
        total_vol = hist.sum()
        target = total_vol * va_pct
        curr = hist[max_idx]
        
        up, down = max_idx, max_idx
        
        # 嚴格邊界檢查 (防止當機)
        while curr < target:
            if up < len(hist)-1 and down > 0:
                if hist[up+1] > hist[down-1]:
                    up += 1
                    curr += hist[up]
                else:
                    down -= 1
                    curr += hist[down]
            elif up < len(hist)-1:
                up += 1
                curr += hist[up]
            elif down > 0:
                down -= 1
                curr += hist[down]
            else:
                break
                
        # 建立回傳數據 (單純的 list)
        vp_data = pd.DataFrame({'Price': bins[:-1], 'Volume': hist})
        return vp_data, poc, bins[up], bins[down]
    except:
        return pd.DataFrame(), 0, 0, 0

# --- 5. 主程式 ---
df = get_data(symbol, timeframe, limit)

if not df.empty:
    vp_df, poc, vah, val = calculate_vp(df, va_percent)
    last = df['Close'].iloc[-1]
    
    # 訊號判斷
    signal, s_color = "WAIT", "gray"
    tp, sl = None, None
    
    if df['Low'].iloc[-1] < val and df['Close'].iloc[-1] > val:
        signal, s_color = "LONG 🟢", "#00FF00"
        sl = df['Low'].iloc[-1]
        tp = last + (last - sl) * risk_reward
    elif df['High'].iloc[-1] > vah and df['Close'].iloc[-1] < vah:
        signal, s_color = "SHORT 🔴", "#FF0000"
        sl = df['High'].iloc[-1]
        tp = last - (sl - last) * risk_reward

    # 顯示數據
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("價格", f"{last:.2f}")
    c2.metric("VAH", f"{vah:.2f}")
    c3.metric("VAL", f"{val:.2f}")
    c4.metric("POC", f"{poc:.2f}")
    c5.markdown(f"### <span style='color:{s_color}'>{signal}</span>", unsafe_allow_html=True)

    # --- 繪圖 (還原成你最喜歡的 Subplot 樣式) ---
    fig = make_subplots(
        rows=1, cols=2, shared_yaxes=True, 
        column_widths=[0.75, 0.25], horizontal_spacing=0.01
    )

    # K線
    fig.add_trace(go.Candlestick(
        x=df.index, open=df['Open'], high=df['High'],
        low=df['Low'], close=df['Close'], name="K線"
    ), row=1, col=1)

    # 關鍵線
    fig.add_hline(y=vah, line_dash="dot", line_color="green", row=1, col=1)
    fig.add_hline(y=val, line_dash="dot", line_color="green", row=1, col=1)
    fig.add_hline(y=poc, line_color="red", line_width=2, row=1, col=1)

    # 訊號
    if signal != "WAIT":
        fig.add_trace(go.Scatter(
            x=[df.index[-1]], y=[last], mode='markers',
            marker=dict(color=s_color, size=15, symbol='star'), name="Signal"
        ), row=1, col=1)
        # 畫 TP/SL
        fig.add_hline(y=tp, line_color=s_color, line_dash="solid", row=1, col=1, annotation_text="TP")
        fig.add_hline(y=sl, line_color="white", line_dash="solid", row=1, col=1, annotation_text="SL")

    # Volume Profile (還原最簡單的顏色邏輯)
    colors = []
    for p in vp_df['Price']:
        if abs(p - poc) < (poc * 0.001): colors.append('red')
        elif val <= p <= vah: colors.append('blue')
        else: colors.append('gray')

    fig.add_trace(go.Bar(
        x=vp_df['Volume'], y=vp_df['Price'], orientation='h',
        marker_color=colors, showlegend=False, name="VP"
    ), row=1, col=2)

    # 設定高度與樣式
    fig.update_layout(height=700, template="plotly_dark", xaxis_rangeslider_visible=False)
    fig.update_xaxes(showticklabels=False, row=1, col=2)

    st.plotly_chart(fig, use_container_width=True)

else:
    st.error("無法獲取數據")
