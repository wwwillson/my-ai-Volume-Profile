import streamlit as st
import ccxt
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import numpy as np
from streamlit_autorefresh import st_autorefresh

# --- 1. 頁面設定 ---
st.set_page_config(page_title="BTC Cloud Bot", layout="wide", page_icon="☁️")

# CSS
st.markdown("""
<style>
    .block-container {padding-top: 1rem; padding-bottom: 2rem;}
</style>
""", unsafe_allow_html=True)

# --- 2. 側邊欄 ---
with st.sidebar:
    st.header("☁️ 雲端交易系統")
    
    # 自動刷新
    if st.toggle("開啟自動刷新 (4分鐘)"):
        count = st_autorefresh(interval=240000, key="refresh")
        st.caption(f"已刷新: {count} 次")

    st.divider()
    
    # --- 關鍵修改：預設改為 Kraken (index=1) ---
    st.info("💡 雲端模式預設使用 Kraken 以防連線被擋")
    # index=1 代表預設選第二個選項 (Kraken)
    source = st.selectbox("數據來源", ["Binance", "Kraken"], index=1)
    
    # 自動調整交易對名稱
    default_symbol = "BTC/USD" if source == "Kraken" else "BTC/USDT"
    symbol = st.text_input("交易對", default_symbol)
    
    timeframe = st.selectbox("週期", ["5m", "15m", "30m", "1h", "4h", "1d"], index=0)
    limit = st.slider("K線數量", 100, 1500, 300)
    
    st.divider()
    st.write("### ⚡ 策略參數")
    va_percent = st.slider("Value Area %", 0.1, 0.9, 0.7)
    risk_reward = st.number_input("盈虧比 (R:R)", value=2.0)
    
    if st.button("🔄 刷新數據"):
        st.cache_data.clear()

    # 交易邏輯
    with st.expander("📖 交易策略邏輯", expanded=True):
        st.markdown("""
        **🟢 做多 (LONG):** 跌破 VAL 後收回。
        **🔴 做空 (SHORT):** 突破 VAH 後跌回。
        *(訊號會以星星圖示標記)*
        """)

# --- 3. 抓取數據 (加入 Timeout) ---
@st.cache_data(ttl=15, show_spinner=False)
def get_data(source, symbol, timeframe, limit):
    try:
        # 設定極短的 timeout (3秒)，如果連不上立刻報錯，不要卡死畫面
        if source == "Binance":
            exchange = ccxt.binance({'enableRateLimit': True, 'timeout': 3000})
        else:
            exchange = ccxt.kraken({'enableRateLimit': True, 'timeout': 3000})
            
        bars = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        
        if not bars: return pd.DataFrame()
        
        df = pd.DataFrame(bars, columns=['timestamp', 'Open', 'High', 'Low', 'Close', 'Volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        return df.astype(float)
    except Exception as e:
        print(f"[ERROR] 連線失敗: {e}")
        return pd.DataFrame()

# --- 4. 計算 VP (防當機版) ---
def calculate_vp(df, va_pct):
    try:
        if df.empty: return None, 0, 0, 0
        
        close = df['Close'].values
        vol = df['Volume'].values
        
        hist, bins = np.histogram(close, bins=120, weights=vol)
        
        max_idx = hist.argmax()
        poc = bins[max_idx]
        
        total_vol = hist.sum()
        target = total_vol * va_pct
        curr = hist[max_idx]
        
        up, down = max_idx, max_idx
        
        while curr < target:
            can_up = up < len(hist) - 1
            can_down = down > 0
            if not can_up and not can_down: break
            
            v_up = hist[up+1] if can_up else -1
            v_down = hist[down-1] if can_down else -1
            
            if v_up >= v_down:
                up += 1
                curr += v_up
            else:
                down -= 1
                curr += v_down
                
        # 轉為 Python List (瀏覽器相容性)
        vp_data = {'Price': bins[:-1].tolist(), 'Volume': hist.tolist()}
        return vp_data, poc, bins[up], bins[down]
    except:
        return None, 0, 0, 0

# --- 5. 主程式 ---
with st.spinner("連線中..."):
    df = get_data(source, symbol, timeframe, limit)

    if not df.empty:
        vp_data, poc, vah, val = calculate_vp(df, va_percent)
        last = df['Close'].iloc[-1]
        
        signal = "WAIT (觀望)"
        s_color = "gray"
        tp, sl = None, None
        
        if df['Low'].iloc[-1] < val and df['Close'].iloc[-1] > val:
            signal = "LONG 🟢"
            s_color = "#00FF00"
            sl = df['Low'].iloc[-1]
            tp = last + (last - sl) * risk_reward
        elif df['High'].iloc[-1] > vah and df['Close'].iloc[-1] < vah:
            signal = "SHORT 🔴"
            s_color = "#FF0000"
            sl = df['High'].iloc[-1]
            tp = last - (sl - last) * risk_reward

        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("價格", f"{last:.2f}")
        c2.metric("VAH", f"{vah:.2f}")
        c3.metric("VAL", f"{val:.2f}")
        c4.metric("POC", f"{poc:.2f}")
        c5.markdown(f"### <span style='color:{s_color}'>{signal}</span>", unsafe_allow_html=True)

        # 繪圖
        fig = make_subplots(
            rows=1, cols=2, shared_yaxes=True, 
            column_widths=[0.75, 0.25], horizontal_spacing=0.01
        )

        fig.add_trace(go.Candlestick(
            x=df.index, open=df['Open'], high=df['High'],
            low=df['Low'], close=df['Close'], name="K線"
        ), row=1, col=1)

        fig.add_hline(y=vah, line_dash="dot", line_color="green", row=1, col=1)
        fig.add_hline(y=val, line_dash="dot", line_color="green", row=1, col=1)
        fig.add_hline(y=poc, line_color="red", line_width=2, row=1, col=1)

        if signal != "WAIT (觀望)":
            fig.add_trace(go.Scatter(
                x=[df.index[-1]], y=[last], mode='markers',
                marker=dict(color=s_color, size=20, symbol='star'), name="Signal"
            ), row=1, col=1)
            fig.add_hline(y=tp, line_color=s_color, line_dash="solid", row=1, col=1, annotation_text="TP")
            fig.add_hline(y=sl, line_color="white", line_dash="solid", row=1, col=1, annotation_text="SL")

        if vp_data:
            colors = []
            for p in vp_data['Price']:
                if abs(p - poc) < (poc * 0.001): colors.append('red')
                elif val <= p <= vah: colors.append('rgba(0, 100, 255, 0.5)')
                else: colors.append('rgba(128, 128, 128, 0.2)')

            fig.add_trace(go.Bar(
                x=vp_data['Volume'], y=vp_data['Price'], orientation='h',
                marker_color=colors, showlegend=False, name="VP"
            ), row=1, col=2)

        fig.update_layout(height=700, template="plotly_dark", xaxis_rangeslider_visible=False)
        fig.update_xaxes(showticklabels=False, row=1, col=2)

        st.plotly_chart(fig, use_container_width=True)

    else:
        st.warning(f"無法從 {source} 獲取數據 (Timeout 或 IP 限制)")
        if source == "Binance":
            st.error("⚠️ 雲端建議使用 **Kraken**，Binance 容易擋 IP。")
