import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import numpy as np
import time

# --- 1. 頁面設定 ---
st.set_page_config(page_title="BTC Cloud Debug", layout="wide")

# --- 2. 模擬數據生成器 (不用連網，保證能跑) ---
def generate_mock_data(limit=300):
    dates = pd.date_range(end=pd.Timestamp.now(), periods=limit, freq='15min')
    np.random.seed(42)
    
    # 隨機漫步生成價格
    close = np.cumsum(np.random.randn(limit)) + 10000
    high = close + np.random.rand(limit) * 10
    low = close - np.random.rand(limit) * 10
    open_ = close - np.random.randn(limit) * 2
    volume = np.abs(np.random.randn(limit) * 1000)
    
    df = pd.DataFrame({
        'timestamp': dates,
        'Open': open_, 'High': high, 'Low': low, 'Close': close, 'Volume': volume
    })
    df.set_index('timestamp', inplace=True)
    return df

# --- 3. 真實數據抓取 (嘗試連網) ---
def get_real_data(exchange_id, symbol, limit):
    import ccxt
    try:
        if exchange_id == 'kraken':
            exchange = ccxt.kraken({'enableRateLimit': True, 'timeout': 3000})
        else:
            exchange = ccxt.binance({'enableRateLimit': True, 'timeout': 3000})
            
        bars = exchange.fetch_ohlcv(symbol, '15m', limit=limit)
        if not bars: return pd.DataFrame()
        
        df = pd.DataFrame(bars, columns=['timestamp', 'Open', 'High', 'Low', 'Close', 'Volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        return df
    except Exception as e:
        st.error(f"連線失敗: {e}")
        return pd.DataFrame()

# --- 4. 計算邏輯 (核心) ---
def calculate_vp(df, va_pct):
    if df.empty: return None, 0, 0, 0
    try:
        close = df['Close'].values
        vol = df['Volume'].values
        
        hist, bins = np.histogram(close, bins=100, weights=vol)
        max_idx = hist.argmax()
        poc = bins[max_idx]
        target = hist.sum() * va_pct
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
                
        return {'p': bins[:-1].tolist(), 'v': hist.tolist()}, poc, bins[up], bins[down]
    except:
        return None, 0, 0, 0

# --- 5. 側邊欄與主介面 ---
with st.sidebar:
    st.header("🛠️ 系統診斷模式")
    
    # 這裡最關鍵：預設選模擬數據，先確保畫面能出來
    data_source = st.radio("數據來源", ["🔹 模擬數據 (測試用)", "🔸 Kraken (真實)", "🔸 Binance (真實)"])
    
    limit = st.slider("K線數量", 100, 1000, 300)
    va_percent = st.slider("VA %", 0.1, 0.9, 0.7)
    risk_reward = st.number_input("盈虧比", 2.0)
    
    # 交易邏輯
    with st.expander("📖 交易策略", expanded=True):
        st.write("""
        **🟢 做多 (LONG):** 跌破 VAL 收回。
        **🔴 做空 (SHORT):** 突破 VAH 跌回。
        """)

# --- 主程式執行 ---
st.title("BTC Volume Profile Analysis")

# 1. 獲取數據
status_text = st.empty()
status_text.info("正在準備數據...")

if "模擬" in data_source:
    df = generate_mock_data(limit)
    symbol_display = "MOCK-BTC"
else:
    exch = 'kraken' if 'Kraken' in data_source else 'binance'
    symbol = 'BTC/USD' if exch == 'kraken' else 'BTC/USDT'
    df = get_real_data(exch, symbol, limit)
    symbol_display = symbol

# 2. 處理與繪圖
if not df.empty:
    status_text.info("數據獲取成功，正在計算 VP...")
    vp_data, poc, vah, val = calculate_vp(df, va_percent)
    last = df['Close'].iloc[-1]
    
    # 訊號
    signal, color, tp, sl = "WAIT", "gray", None, None
    if df['Low'].iloc[-1] < val and df['Close'].iloc[-1] > val:
        signal, color = "LONG 🟢", "#00FF00"
        sl = df['Low'].iloc[-1]
        tp = last + (last - sl) * risk_reward
    elif df['High'].iloc[-1] > vah and df['Close'].iloc[-1] < vah:
        signal, color = "SHORT 🔴", "#FF0000"
        sl = df['High'].iloc[-1]
        tp = last - (sl - last) * risk_reward

    # 顯示指標
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("價格", f"{last:.2f}")
    c2.metric("VAH", f"{vah:.2f}")
    c3.metric("VAL", f"{val:.2f}")
    c4.metric("POC", f"{poc:.2f}")
    
    if signal != "WAIT":
        st.success(f"訊號觸發: {signal}")
    
    # 繪圖
    status_text.info("正在繪製圖表...")
    fig = make_subplots(rows=1, cols=2, shared_yaxes=True, column_widths=[0.75, 0.25])
    
    # K線
    fig.add_trace(go.Candlestick(
        x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'],
        name="Price"
    ), row=1, col=1)
    
    # 線
    fig.add_hline(y=vah, line_color="green", line_dash="dot", row=1, col=1)
    fig.add_hline(y=val, line_color="green", line_dash="dot", row=1, col=1)
    fig.add_hline(y=poc, line_color="red", row=1, col=1)
    
    # 訊號標記
    if signal != "WAIT":
        fig.add_trace(go.Scatter(
            x=[df.index[-1]], y=[last], mode='markers',
            marker=dict(color=color, size=15, symbol='star'), name="Signal"
        ), row=1, col=1)
        fig.add_hline(y=tp, line_color=color, row=1, col=1)
        fig.add_hline(y=sl, line_color="white", row=1, col=1)

    # VP
    if vp_data:
        colors = ['red' if abs(p-poc)<poc*0.001 else 'blue' if val<=p<=vah else 'gray' for p in vp_data['p']]
        fig.add_trace(go.Bar(
            x=vp_data['v'], y=vp_data['p'], orientation='h',
            marker_color=colors, showlegend=False
        ), row=1, col=2)

    fig.update_layout(height=600, template="plotly_dark", xaxis_rangeslider_visible=False)
    fig.update_xaxes(showticklabels=False, row=1, col=2)
    
    st.plotly_chart(fig, use_container_width=True)
    status_text.success("✅ 載入完成")

else:
    status_text.error("無法載入數據。如果是選真實交易所，代表雲端 IP 被擋。請切換回模擬數據測試。")
