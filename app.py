import streamlit as st
import pandas as pd
import plotly.graph_objects as go

# 設定網頁標題與寬度
st.set_page_config(page_title="台指選點位戰法", layout="wide")

st.title("⚔️ 台指選擇權：攻守點位戰法")

# --- 側邊欄：設定 ---
st.sidebar.header("1. 趨勢設定")
direction = st.sidebar.radio("您目前看哪個方向？", ["看漲 (Buy Call)", "看跌 (Buy Put)"])

st.sidebar.header("2. 防守邏輯 (停損)")
stop_mode = st.sidebar.selectbox(
    "防守點位依據", 
    ["昨日低點/高點 (激進)", "MA5 (短線)", "MA20 (波段)", "自訂點數"]
)

custom_stop_pts = 0
if stop_mode == "自訂點數":
    custom_stop_pts = st.sidebar.number_input("停損點數 (距離進場價)", value=100, step=10)

st.sidebar.header("3. 攻擊邏輯 (加碼)")
add_on_ratio = st.sidebar.slider("獲利加碼比 (Risk:Reward)", 1.0, 3.0, 1.5, 0.5, help="當獲利達到停損風險的幾倍時加碼？設 1.0 代表賺賠比 1:1 時加碼")

st.sidebar.markdown("---")
kline_file = st.sidebar.file_uploader("上傳加權指數 K 線", type=['csv', 'xlsx', 'xls'])
option_file = st.sidebar.file_uploader("上傳選擇權報價", type=['csv', 'xlsx', 'xls'])

# --- 核心邏輯 ---
@st.cache_data
def load_data(k_file, op_file):
    # (維持原本的讀取邏輯，為節省篇幅省略部分重複代碼，功能不變)
    # K線讀取
    try:
        if k_file.name.lower().endswith('.csv'): df_k = pd.read_csv(k_file)
        else: df_k = pd.read_excel(k_file)
        df_k.columns = [str(c).strip() for c in df_k.columns]
        if '時間' in df_k.columns: df_k.rename(columns={'時間': 'Date'}, inplace=True)
        if 'Date' in df_k.columns: df_k['Date'] = pd.to_datetime(df_k['Date']); df_k = df_k.sort_values('Date')
        for c in ['收盤價', '開盤價', '最高價', '最低價', 'SMA5', 'SMA20']:
            if c in df_k.columns: df_k[c] = pd.to_numeric(df_k[c], errors='coerce')
    except: return None, None

    # 選擇權讀取
    try:
        if op_file.name.lower().endswith('.csv'): 
            try: df_op = pd.read_csv(op_file, encoding='utf-8')
            except: df_op = pd.read_csv(op_file, encoding='big5')
        else: df_op = pd.read_excel(op_file)
        df_op.columns = [str(c).strip() for c in df_op.columns]
        if '成交' in df_op.columns: df_op['成交'] = pd.to_numeric(df_op['成交'], errors='coerce'); df_op = df_op.dropna(subset=['成交'])
        
        def parse_row(row_str):
            try:
                parts = str(row_str).split()
                strike = int([p for p in parts if p.isdigit() and int(p) > 10000][0])
                type_ = 'Call' if 'C' in parts or 'Call' in parts else ('Put' if 'P' in parts or 'Put' in parts else None)
                return type_, strike
            except: return None, None

        if '商品' in df_op.columns and 'Strike' not in df_op.columns:
            parsed = df_op['商品'].apply(parse_row)
            df_op['Type'], df_op['Strike'] = parsed.apply(lambda x: x[0]), parsed.apply(lambda x: x[1])
    except: return None, None
    
    return df_k, df_op

# --- 主程式 ---
if kline_file and option_file:
    df_k, df_op = load_data(kline_file, option_file)
    
    if df_k is not None and not df_k.empty:
        last_k = df_k.iloc[-1]
        prev_k = df_k.iloc[-2] # 昨日 K 線
        current_price = last_k['收盤價']
        
        # === 1. 計算關鍵點位 ===
        entry_price = current_price
        stop_price = 0
        
        # 根據方向決定邏輯
        is_bull = "Call" in direction
        
        # 計算防守點 (Stop Loss)
        if stop_mode == "自訂點數":
            stop_price = entry_price - custom_stop_pts if is_bull else entry_price + custom_stop_pts
        elif stop_mode == "MA5 (短線)":
            stop_price = last_k['SMA5']
        elif stop_mode == "MA20 (波段)":
            stop_price = last_k['SMA20']
        else: # 昨日高低點
            stop_price = prev_k['最低價'] if is_bull else prev_k['最高價']

        # 計算風險值 (Risk)
        risk_dist = abs(entry_price - stop_price)
        
        # 計算攻擊點 (加碼點 Add-on) = 進場 + (風險 * 倍率)
        if is_bull:
            add_on_price = entry_price + (risk_dist * add_on_ratio)
        else:
            add_on_price = entry_price - (risk_dist * add_on_ratio)

        # === 2. 顯示戰情儀表板 ===
        c1, c2, c3 = st.columns(3)
        c1.metric("📉 防守點 (停損)", f"{stop_price:,.0f}", f"-{risk_dist:,.0f} 點")
        c2.metric("🔵 進場點 (現價)", f"{entry_price:,.0f}", "Base")
        c3.metric("🚀 攻擊點 (加碼)", f"{add_on_price:,.0f}", f"+{abs(add_on_price-entry_price):,.0f} 點")

        st.info(f"💡 **戰略說明**：若指數來到 **{add_on_price:,.0f}**，代表趨勢正確，可進行加碼攻擊；若觸及 **{stop_price:,.0f}**，請務必執行防守(平倉)。")

        # === 3. 繪製互動圖表 ===
        fig = go.Figure(data=[go.Candlestick(
            x=df_k['Date'], open=df_k['開盤價'], high=df_k['最高價'],
            low=df_k['最低價'], close=df_k['收盤價'], name='K線'
        )])
        
        # 畫均線
        if 'SMA5' in df_k.columns: fig.add_trace(go.Scatter(x=df_k['Date'], y=df_k['SMA5'], line=dict(color='orange', width=1), name='MA5'))
        if 'SMA20' in df_k.columns: fig.add_trace(go.Scatter(x=df_k['Date'], y=df_k['SMA20'], line=dict(color='blue', width=1), name='MA20'))

        # 畫戰略線 (只畫在最後一段時間，避免圖表太亂)
        start_date = df_k['Date'].iloc[-10] # 只畫最近10天長度
        end_date = df_k['Date'].iloc[-1]
        
        # 停損線 (紅/綠虛線)
        fig.add_shape(type="line", x0=start_date, y0=stop_price, x1=end_date, y1=stop_price,
                      line=dict(color="Red" if is_bull else "Green", width=2, dash="dash"))
        fig.add_annotation(x=end_date, y=stop_price, text="防守(停損)", showarrow=False, yshift=10)

        # 進場線 (灰線)
        fig.add_shape(type="line", x0=start_date, y0=entry_price, x1=end_date, y1=entry_price,
                      line=dict(color="Gray", width=1, dash="dot"))
        fig.add_annotation(x=end_date, y=entry_price, text="進場", showarrow=False, yshift=10)

        # 攻擊線 (金線)
        fig.add_shape(type="line", x0=start_date, y0=add_on_price, x1=end_date, y1=add_on_price,
                      line=dict(color="Gold", width=3))
        fig.add_annotation(x=end_date, y=add_on_price, text="攻擊(加碼)", showarrow=False, yshift=10)

        st.plotly_chart(fig, use_container_width=True)

        # === 4. 資金試算 (結合選擇權報價) ===
        st.divider()
        st.subheader("💰 實戰資金試算")
        
        # 抓取 ATM 報價
        if df_op is not None and 'Strike' in df_op.columns:
            strikes = sorted(df_op['Strike'].dropna().unique())
            atm_strike = min(strikes, key=lambda x: abs(x - current_price))
            op_type = 'Call' if is_bull else 'Put'
            target_op = df_op[(df_op['Strike'] == atm_strike) & (df_op['Type'] == op_type)]
            
            if not target_op.empty:
                op_price = target_op.iloc[0]['成交']
                lot_cost = op_price * 50
                
                st.write(f"🎯 鎖定合約：**{op_type} {atm_strike}** (報價: {op_price})")
                st.write(f"🔹 買進 1 口成本: **NT$ {lot_cost:,.0f}**")
                
                # 簡單損益預估
                delta = 0.5 # 假設價平 Delta 約 0.5
                est_loss = risk_dist * delta * 50
                st.warning(f"⚠️ 若觸及防守點 ({stop_price:,.0f})，預估每口虧損約：**NT$ {est_loss:,.0f}**")
            else:
                st.warning("查無對應選擇權報價")

else:
    st.info("👈 請上傳 K 線與報價表以開始分析")
