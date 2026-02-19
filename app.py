import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import numpy as np

# 設定網頁標題與寬度
st.set_page_config(page_title="台指選擇權決策支援系統", layout="wide")

# --- 標題區 ---
st.title("📊 台指選擇權 (TXO) 買方策略分析工具")
st.markdown("針對 **Buy Call / Buy Put** 策略設計，支援 .xlsx / .xls / .csv 格式。")

# --- 側邊欄：資料上傳 ---
st.sidebar.header("📁 資料上傳")
# 修改點：type 加入 'xls'
kline_file = st.sidebar.file_uploader("上傳加權指數 K 線", type=['csv', 'xlsx', 'xls'])
option_file = st.sidebar.file_uploader("上傳選擇權報價", type=['csv', 'xlsx', 'xls'])

# --- 核心邏輯函數 ---

@st.cache_data
def load_kline(file):
    try:
        if file.name.lower().endswith('.csv'):
            df = pd.read_csv(file)
        else:
            # pd.read_excel 同時支援 xls 與 xlsx，但需要對應的引擎 (xlrd/openpyxl)
            df = pd.read_excel(file)
        
        # 欄位名稱標準化 (去除空白)
        df.columns = [str(c).strip() for c in df.columns]
        
        # 處理日期 (相容常見中文欄位)
        if '時間' in df.columns:
            df.rename(columns={'時間': 'Date'}, inplace=True)
        
        if 'Date' in df.columns:
            df['Date'] = pd.to_datetime(df['Date'])
            df = df.sort_values('Date')
        
        # 確保數值欄位正確
        cols = ['收盤價', '開盤價', '最高價', '最低價', 'SMA5', 'SMA20']
        for c in cols:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors='coerce')
                
        return df
    except Exception as e:
        st.error(f"K 線資料讀取錯誤: {e}")
        return None

@st.cache_data
def load_options(file):
    try:
        if file.name.lower().endswith('.csv'):
            try:
                df = pd.read_csv(file, encoding='utf-8')
            except:
                df = pd.read_csv(file, encoding='big5')
        else:
            # 支援 xls 與 xlsx
            df = pd.read_excel(file)

        # 欄位名稱標準化
        df.columns = [str(c).strip() for c in df.columns]

        # 清洗成交價
        if '成交' in df.columns:
            df['成交'] = pd.to_numeric(df['成交'], errors='coerce')
            df = df.dropna(subset=['成交'])

        # 解析商品名稱取得 Strike 與 Type
        # 邏輯：解析字串 (例如 "台指選02 C 33600")
        def parse_row(row_str):
            try:
                parts = str(row_str).split()
                strike = None
                type_ = None
                for p in parts:
                    # 簡單判斷：大於 10000 的整數通常是履約價
                    if p.isdigit() and int(p) > 10000: 
                        strike = int(p)
                    if p in ['C', 'Call']: type_ = 'Call'
                    if p in ['P', 'Put']: type_ = 'Put'
                return type_, strike
            except:
                return None, None

        if '商品' in df.columns and 'Type' not in df.columns:
            parsed = df['商品'].apply(parse_row)
            df['Type'] = parsed.apply(lambda x: x[0])
            df['Strike'] = parsed.apply(lambda x: x[1])
            
        return df
    except Exception as e:
        st.error(f"選擇權資料讀取錯誤: {e}")
        return None

# --- 主畫面邏輯 ---

if kline_file is not None and option_file is not None:
    # 1. 處理資料
    df_k = load_kline(kline_file)
    df_op = load_options(option_file)

    if df_k is not None and df_op is not None and not df_k.empty:
        
        # 取得最新一筆 K 線資料
        last_k = df_k.iloc[-1]
        
        # 容錯處理：確保有收盤價
        if '收盤價' in last_k:
            current_price = last_k['收盤價']
            date_display = last_k['Date'].strftime('%Y-%m-%d') if 'Date' in df_k.columns else "最新"
            
            # --- 版面配置：上方 K 線圖 ---
            st.subheader(f"📈 加權指數趨勢 (最新收盤: {current_price:,.0f} @ {date_display})")
            
            # 繪製 K 線圖
            fig = go.Figure(data=[go.Candlestick(
                x=df_k['Date'] if 'Date' in df_k.columns else df_k.index,
                open=df_k['開盤價'], high=df_k['最高價'],
                low=df_k['最低價'], close=df_k['收盤價'], name='K線'
            )])
            
            # 加入均線 (如果有)
            if 'SMA5' in df_k.columns:
                fig.add_trace(go.Scatter(x=df_k['Date'], y=df_k['SMA5'], line=dict(color='orange', width=1), name='MA5'))
            if 'SMA20' in df_k.columns:
                fig.add_trace(go.Scatter(x=df_k['Date'], y=df_k['SMA20'], line=dict(color='blue', width=1), name='MA20'))

            fig.update_layout(height=400, margin=dict(l=20, r=20, t=20, b=20), xaxis_rangeslider_visible=False)
            st.plotly_chart(fig, use_container_width=True)

            # --- 趨勢判斷 ---
            col_t1, col_t2, col_t3 = st.columns(3)
            
            ma5 = last_k.get('SMA5', 0)
            ma20 = last_k.get('SMA20', 0)
            
            # 簡單趨勢評分
            trend_score = 0
            if ma5 > 0 and current_price > ma5: trend_score += 1
            if ma20 > 0 and current_price > ma20: trend_score += 1
            if ma5 > 0 and ma20 > 0 and ma5 > ma20: trend_score += 1
            
            with col_t1:
                st.metric("MA5 (短期成本)", f"{ma5:,.0f}", delta=f"{current_price - ma5:,.0f}" if ma5 else None)
            with col_t2:
                st.metric("MA20 (月線支撐)", f"{ma20:,.0f}", delta=f"{current_price - ma20:,.0f}" if ma20 else None)
            with col_t3:
                if trend_score >= 2:
                    st.success("🔥 目前趨勢：偏多 (Bullish)")
                elif trend_score <= 1:
                    st.error("❄️ 目前趨勢：偏空 (Bearish)")
                else:
                    st.warning("⚖️ 目前趨勢：盤整 (Neutral)")

            st.divider()

            # --- 策略與成本計算區 ---
            st.subheader("💰 選擇權買方策略計算 (Buy Call / Buy Put)")

            # 尋找價平 (ATM)
            if 'Strike' in df_op.columns:
                valid_strikes = df_op['Strike'].dropna().unique()
                if len(valid_strikes) > 0:
                    strikes = sorted(valid_strikes)
                    # 找到最接近 current_price 的值
                    atm_strike = min(strikes, key=lambda x: abs(x - current_price))
                    
                    st.info(f"🎯 系統鎖定價平履約價 (ATM Strike): **{atm_strike}**")

                    # 抓取該履約價的 Call 與 Put 價格
                    target_call = df_op[(df_op['Strike'] == atm_strike) & (df_op['Type'] == 'Call')]
                    target_put = df_op[(df_op['Strike'] == atm_strike) & (df_op['Type'] == 'Put')]

                    c1, c2 = st.columns(2)

                    # --- Buy Call 卡片 ---
                    with c1:
                        st.markdown("### 🐂 看漲 (Buy Call)")
                        if not target_call.empty:
                            price = target_call.iloc[0]['成交']
                            cost = price * 50
                            st.metric("權利金報價", f"{price} 點")
                            st.markdown(f"#### 所需金額: <span style='color:#ff4b4b'>NT$ {cost:,.0f}</span>", unsafe_allow_html=True)
                        else:
                            st.warning("查無此履約價之 Call 報價")

                    # --- Buy Put 卡片 ---
                    with c2:
                        st.markdown("### 🐻 看跌 (Buy Put)")
                        if not target_put.empty:
                            price = target_put.iloc[0]['成交']
                            cost = price * 50
                            st.metric("權利金報價", f"{price} 點")
                            st.markdown(f"#### 所需金額: <span style='color:#2bd600'>NT$ {cost:,.0f}</span>", unsafe_allow_html=True)
                        else:
                            st.warning("查無此履約價之 Put 報價")
                else:
                    st.error("選擇權資料中未發現有效的履約價 (Strike)。")
            else:
                st.error("無法解析選擇權履約價，請檢查檔案 '商品' 欄位格式。")
        else:
            st.error("K 線資料中找不到 '收盤價' 欄位。")
    else:
        st.warning("資料解析失敗或內容為空。")

else:
    st.info("👈 請從側邊欄上傳 `加權指數` 與 `選擇權報價` (支援 .xlsx / .xls / .csv)。")