import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import numpy as np
from streamlit_autorefresh import st_autorefresh
import ccxt

# --- 1. 頁面設定 ---
st.set_page_config(page_title="BTC Pro Trading", layout="wide", page_icon="📊")

# CSS 優化
st.markdown("""
<style>
    .block-container {padding-top: 1rem; padding-bottom: 3rem;}
    .stPlotlyChart {background-color: #0E1117; border-radius: 5px;}
</style>
""", unsafe_allow_html=True)

# --- 2. 側邊欄：控制台 ---
with st.sidebar:
    st.title("⚙️ 交易控制台")
    
    # [需求] 2分鐘自動刷新
    if st.toggle("開啟自動刷新 (1分鐘)", value=False):
        # interval 單位是毫秒: 1 * 60 * 1000 = 120000
        count = st_autorefresh(interval=60000, limit=None, key="auto_refresh")
        st.caption(f"監控中... (刷新次數: {count})")

    st.divider()
    
    # [需求] 數據源切換 (解決雲端卡頓問題)
    data_source = st.selectbox(
        "數據來源", 
        ["🔹 模擬數據 (測試用)", "🔸 Kraken (推薦)", "🔸 Binance (易擋IP)"],
        index=1 # 預設選 Kraken，兼顧速度與真實性
    )
    
    # 自動設定交易對
    if "模擬" in data_source:
        default_symbol = "MOCK-BTC"
    elif "Kraken" in data_source:
        default_symbol = "BTC/USD"
    else:
        default_symbol = "BTC/USDT"
        
    symbol = st.text_input("交易對", default_symbol)
    
    # [需求] 週期選擇
    timeframe = st.selectbox("時間週期", ["1m", "5m", "15m", "30m", "1h", "4h", "1d"], index=2)
    limit = st.slider("K線數量", 100, 2000, 300)
    
    st.divider()
    st.write("### ⚡ 策略參數")
    va_percent = st.slider("Value Area %", 0.1, 0.9, 0.7)
    risk_reward = st.number_input("盈虧比 (R:R)", value=2.0)
    
    if st.button("🔄 手動刷新", type="primary"):
        st.cache_data.clear()

    # 交易邏輯說明
    with st.expander("📖 交易策略邏輯", expanded=True):
        st.markdown("""
        **核心概念：Volume Profile 均值回歸**
        
        **🟢 做多 (LONG) 訊號：**
        1. 價格跌破 **VAL** (價值低點)。
        2. 收盤價 **收回 VAL 之上** (假跌破)。
        3. 圖表顯示：<span style='color:#00FF00'>**綠色星星 ★**</span>
        
        **🔴 做空 (SHORT) 訊號：**
        1. 價格突破 **VAH** (價值高點)。
        2. 收盤價 **跌回 VAH 之下** (假突破)。
        3. 圖表顯示：<span style='color:#FF0000'>**紅色星星 ★**</span>
        """, unsafe_allow_html=True)

# --- 3. 數據處理核心函數 ---

# A. 產生模擬數據 (不用連網，保證有畫面)
def generate_mock_data(limit):
    dates = pd.date_range(end=pd.Timestamp.now(), periods=limit, freq='15min')
    np.random.seed(int(pd.Timestamp.now().timestamp())) # 隨機亂數
    
    close = np.cumsum(np.random.randn(limit)) + 90000
    high = close + np.abs(np.random.randn(limit) * 100)
    low = close - np.abs(np.random.randn(limit) * 100)
    open_ = close + np.random.randn(limit) * 50
    volume = np.abs(np.random.randn(limit) * 1000) + 500
    
    df = pd.DataFrame({
        'timestamp': dates, 'Open': open_, 'High': high, 'Low': low, 'Close': close, 'Volume': volume
    })
    df.set_index('timestamp', inplace=True)
    return df

# B. 抓取真實數據 (加入 Timeout)
@st.cache_data(ttl=15, show_spinner=False)
def get_real_data(source_name, symbol, timeframe, limit):
    try:
        if "Kraken" in source_name:
            exchange = ccxt.kraken({'enableRateLimit': True, 'timeout': 5000})
        else:
            exchange = ccxt.binance({'enableRateLimit': True, 'timeout': 5000})
            
        bars = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        if not bars: return pd.DataFrame()
        
        df = pd.DataFrame(bars, columns=['timestamp', 'Open', 'High', 'Low', 'Close', 'Volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        return df.astype(float)
    except Exception as e:
        print(f"[Error] {e}")
        return pd.DataFrame()

# C. 計算 Volume Profile (嚴格防當機版)
def calculate_vp(df, va_pct):
    if df.empty: return None, 0, 0, 0
    try:
        close = df['Close'].values
        vol = df['Volume'].values
        
        # 使用 Numpy 計算分佈
        hist, bins = np.histogram(close, bins=120, weights=vol)
        
        max_idx = hist.argmax()
        poc = bins[max_idx]
        
        target = hist.sum() * va_pct
        curr = hist[max_idx]
        up, down = max_idx, max_idx
        
        # 擴散算法
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
                
        # 轉換為 List 格式回傳 (這是解決白畫面的關鍵)
        vp_data = {
            'price': bins[:-1].tolist(),
            'volume': hist.tolist()
        }
        return vp_data, poc, bins[up], bins[down]
    except:
        return None, 0, 0, 0

# --- 4. 主程式邏輯 ---
status_text = st.empty() # 狀態列

# 1. 決定數據源
if "模擬" in data_source:
    status_text.info("🛠️ 正在生成模擬數據...")
    df = generate_mock_data(limit)
else:
    status_text.info(f"🌐 正在連線 {data_source} ({symbol}, {timeframe})...")
    df = get_real_data(data_source, symbol, timeframe, limit)

# 2. 處理與繪圖
if not df.empty:
    status_text.info("正在計算 Volume Profile...")
    vp_data, poc, vah, val = calculate_vp(df, va_percent)
    
    if vp_data:
        last = df['Close'].iloc[-1]
        
        # --- 訊號判定 ---
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

        # --- 顯示指標 ---
        status_text.empty() # 清除狀態文字
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("價格", f"{last:.2f}")
        c2.metric("VAH", f"{vah:.2f}")
        c3.metric("VAL", f"{val:.2f}")
        c4.metric("POC", f"{poc:.2f}")
        c5.markdown(f"### <span style='color:{s_color}'>{signal}</span>", unsafe_allow_html=True)

        # --- 繪圖 (使用 Python List 確保穩定性) ---
        fig = make_subplots(
            rows=1, cols=2, shared_yaxes=True, 
            column_widths=[0.75, 0.25], horizontal_spacing=0.01,
            subplot_titles=(f"{symbol} 走勢圖", "籌碼分佈")
        )

        # K線
        fig.add_trace(go.Candlestick(
            x=df.index, open=df['Open'], high=df['High'],
            low=df['Low'], close=df['Close'], name="K線"
        ), row=1, col=1)

        # 關鍵線位
        fig.add_hline(y=vah, line_dash="dot", line_color="green", row=1, col=1, annotation_text="VAH")
        fig.add_hline(y=val, line_dash="dot", line_color="green", row=1, col=1, annotation_text="VAL")
        fig.add_hline(y=poc, line_color="red", line_width=2, row=1, col=1, annotation_text="POC")

        # 訊號標記
        if signal != "WAIT (觀望)":
            fig.add_trace(go.Scatter(
                x=[df.index[-1]], y=[last], mode='markers',
                marker=dict(color=s_color, size=20, symbol='star'), name="Signal"
            ), row=1, col=1)
            fig.add_hline(y=tp, line_color=s_color, line_dash="solid", row=1, col=1, annotation_text="TP")
            fig.add_hline(y=sl, line_color="white", line_dash="solid", row=1, col=1, annotation_text="SL")

        # VP 直方圖 (顏色處理)
        colors = []
        for p in vp_data['price']:
            if abs(p - poc) < (poc * 0.001):
                colors.append('red')
            elif val <= p <= vah:
                colors.append('rgba(0, 100, 255, 0.5)')
            else:
                colors.append('rgba(128, 128, 128, 0.2)')

        fig.add_trace(go.Bar(
            x=vp_data['volume'], y=vp_data['price'], orientation='h',
            marker_color=colors, showlegend=False, name="Vol"
        ), row=1, col=2)

        # 樣式
        fig.update_layout(
            height=700, 
            template="plotly_dark",
            margin=dict(l=10, r=10, t=30, b=10),
            xaxis_rangeslider_visible=False,
            hovermode="y unified"
        )
        fig.update_xaxes(showticklabels=False, row=1, col=2)

        st.plotly_chart(fig, use_container_width=True)

    else:
        st.error("VP 計算失敗，請嘗試調整 K 線數量。")
else:
    if "模擬" not in data_source:
        st.warning("⚠️ 無法獲取數據。雲端環境請使用 **Kraken**，或是暫時使用 **模擬數據** 檢查功能。")
