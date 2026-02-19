import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import numpy as np

# 設定網頁標題與寬度
st.set_page_config(page_title="台指選擇權資金攻守策略", layout="wide")

# --- 側邊欄：資金與檔案設定 ---
st.sidebar.header("💰 資金與策略設定")

# 1. 資金輸入
total_capital = st.sidebar.number_input("總操作資金 (TWD)", min_value=10000, value=100000, step=10000)

# 2. 攻守模式設定
st.sidebar.markdown("---")
st.sidebar.header("⚔️ 攻守模式定義")
def_pct = st.sidebar.slider("🛡️ 防守模式 (投入資金 %)", 1, 20, 5, help="試單或風險較高時，只投入總資金的多少百分比")
atk_pct = st.sidebar.slider("⚔️ 攻擊模式 (投入資金 %)", 10, 100, 30, help="趨勢確立時，投入總資金的多少百分比")

st.sidebar.markdown("---")
st.sidebar.header("📁 資料上傳")
kline_file = st.sidebar.file_uploader("上傳加權指數 K 線", type=['csv', 'xlsx', 'xls'])
option_file = st.sidebar.file_uploader("上傳選擇權報價", type=['csv', 'xlsx', 'xls'])

# --- 核心邏輯函數 (維持不變) ---

@st.cache_data
def load_kline(file):
    try:
        if file.name.lower().endswith('.csv'):
            df = pd.read_csv(file)
        else:
            df = pd.read_excel(file)
        
        df.columns = [str(c).strip() for c in df.columns]
        
        if '時間' in df.columns: df.rename(columns={'時間': 'Date'}, inplace=True)
        if 'Date' in df.columns:
            df['Date'] = pd.to_datetime(df['Date'])
            df = df.sort_values('Date')
        
        cols = ['收盤價', '開盤價', '最高價', '最低價', 'SMA5', 'SMA20']
        for c in cols:
            if c in df.columns: df[c] = pd.to_numeric(df[c], errors='coerce')
        return df
    except Exception as e:
        st.error(f"K 線資料讀取錯誤: {e}")
        return None

@st.cache_data
def load_options(file):
    try:
        if file.name.lower().endswith('.csv'):
            try: df = pd.read_csv(file, encoding='utf-8')
            except: df = pd.read_csv(file, encoding='big5')
        else:
            df = pd.read_excel(file)

        df.columns = [str(c).strip() for c in df.columns]
        if '成交' in df.columns:
            df['成交'] = pd.to_numeric(df['成交'], errors='coerce')
            df = df.dropna(subset=['成交'])

        def parse_row(row_str):
            try:
                parts = str(row_str).split()
                strike = None
                type_ = None
                for p in parts:
                    if p.isdigit() and int(p) > 10000: strike = int(p)
                    if p in ['C', 'Call']: type_ = 'Call'
                    if p in ['P', 'Put']: type_ = 'Put'
                return type_, strike
            except: return None, None

        if '商品' in df.columns and 'Type' not in df.columns:
            parsed = df['商品'].apply(parse_row)
            df['Type'] = parsed.apply(lambda x: x[0])
            df['Strike'] = parsed.apply(lambda x: x[1])
        return df
    except Exception as e:
        st.error(f"選擇權資料讀取錯誤: {e}")
        return None

# --- 計算口數函數 ---
def calculate_position(capital, percent, price):
    """
    計算可下單口數
    capital: 總資金
    percent: 投入百分比 (0-100)
    price: 選擇權點數
    """
    budget = capital * (percent / 100)
    cost_per_lot = price * 50
    if cost_per_lot == 0: return 0, 0, 0
    
    lots = int(budget // cost_per_lot)
    actual_cost = lots * cost_per_lot
    return lots, actual_cost, budget

# --- 主畫面邏輯 ---

st.title("🛡️ 選擇權資金攻守策略系統")
st.markdown(f"目前總資金: **NT$ {total_capital:,.0f}** | 防守倉位: **{def_pct}%** | 攻擊倉位: **{atk_pct}%**")

if kline_file is not None and option_file is not None:
    df_k = load_kline(kline_file)
    df_op = load_options(option_file)

    if df_k is not None and df_op is not None and not df_k.empty:
        last_k = df_k.iloc[-1]
        if '收盤價' in last_k:
            current_price = last_k['收盤價']
            
            # --- 1. K線圖與趨勢 (精簡顯示) ---
            with st.expander("📈 展開查看 K 線圖與技術指標", expanded=True):
                fig = go.Figure(data=[go.Candlestick(
                    x=df_k['Date'] if 'Date' in df_k.columns else df_k.index,
                    open=df_k['開盤價'], high=df_k['最高價'],
                    low=df_k['最低價'], close=df_k['收盤價'], name='K線')])
                
                if 'SMA5' in df_k.columns: fig.add_trace(go.Scatter(x=df_k['Date'], y=df_k['SMA5'], line=dict(color='orange'), name='MA5'))
                if 'SMA20' in df_k.columns: fig.add_trace(go.Scatter(x=df_k['Date'], y=df_k['SMA20'], line=dict(color='blue'), name='MA20'))
                
                fig.update_layout(height=350, margin=dict(t=10, b=10))
                st.plotly_chart(fig, use_container_width=True)

                # 趨勢訊號
                ma5 = last_k.get('SMA5', 0)
                ma20 = last_k.get('SMA20', 0)
                trend_text = "盤整 (Neutral)"
                trend_color = "gray"
                
                if current_price > ma5 and current_price > ma20 and ma5 > ma20:
                    trend_text = "強多頭 (Strong Bull) 👉 適合攻擊"
                    trend_color = "red"
                elif current_price < ma5 and current_price < ma20 and ma5 < ma20:
                    trend_text = "強空頭 (Strong Bear) 👉 適合攻擊"
                    trend_color = "green"
                else:
                    trend_text = "震盪整理 (Consolidation) 👉 建議防守或觀望"
                    trend_color = "orange"
                
                st.markdown(f"#### 系統判斷趨勢：<span style='color:{trend_color}'>{trend_text}</span>", unsafe_allow_html=True)

            # --- 2. 選擇權策略核心區 ---
            st.divider()
            
            # 尋找價平
            if 'Strike' in df_op.columns:
                valid_strikes = df_op['Strike'].dropna().unique()
                if len(valid_strikes) > 0:
                    strikes = sorted(valid_strikes)
                    atm_strike = min(strikes, key=lambda x: abs(x - current_price))
                    
                    target_call = df_op[(df_op['Strike'] == atm_strike) & (df_op['Type'] == 'Call')]
                    target_put = df_op[(df_op['Strike'] == atm_strike) & (df_op['Type'] == 'Put')]

                    # 介面佈局
                    col_call, col_mid, col_put = st.columns([1, 0.2, 1])

                    # === 左側：Buy Call ===
                    with col_call:
                        st.subheader("🐂 看漲 (Buy Call)")
                        if not target_call.empty:
                            price = target_call.iloc[0]['成交']
                            st.metric("履約價", f"{atm_strike}", f"報價: {price}")
                            
                            # 計算攻守
                            def_lots, def_cost, def_budget = calculate_position(total_capital, def_pct, price)
                            atk_lots, atk_cost, atk_budget = calculate_position(total_capital, atk_pct, price)

                            tab1, tab2 = st.tabs(["🛡️ 防守下單", "⚔️ 攻擊下單"])
                            
                            with tab1:
                                st.info(f"**防守策略 ({def_pct}%)**")
                                st.write(f"建議口數: **{def_lots} 口**")
                                st.write(f"預估成本: ${def_cost:,.0f}")
                                st.caption(f"保留資金: ${total_capital - def_cost:,.0f}")
                                if def_lots == 0: st.warning("資金不足以購買 1 口")

                            with tab2:
                                st.error(f"**攻擊策略 ({atk_pct}%)**")
                                st.write(f"建議口數: **{atk_lots} 口**")
                                st.write(f"預估成本: ${atk_cost:,.0f}")
                                st.caption(f"保留資金: ${total_capital - atk_cost:,.0f}")
                        else:
                            st.warning("無報價")

                    # === 中間：分隔線 ===
                    with col_mid:
                        st.markdown("<div style='height: 300px; border-left: 1px solid #ccc;'></div>", unsafe_allow_html=True)

                    # === 右側：Buy Put ===
                    with col_put:
                        st.subheader("🐻 看跌 (Buy Put)")
                        if not target_put.empty:
                            price = target_put.iloc[0]['成交']
                            st.metric("履約價", f"{atm_strike}", f"報價: {price}")

                            # 計算攻守
                            def_lots, def_cost, def_budget = calculate_position(total_capital, def_pct, price)
                            atk_lots, atk_cost, atk_budget = calculate_position(total_capital, atk_pct, price)

                            tab1, tab2 = st.tabs(["🛡️ 防守下單", "⚔️ 攻擊下單"])
                            
                            with tab1:
                                st.info(f"**防守策略 ({def_pct}%)**")
                                st.write(f"建議口數: **{def_lots} 口**")
                                st.write(f"預估成本: ${def_cost:,.0f}")
                                st.caption(f"保留資金: ${total_capital - def_cost:,.0f}")
                                if def_lots == 0: st.warning("資金不足以購買 1 口")

                            with tab2:
                                st.success(f"**攻擊策略 ({atk_pct}%)**")
                                st.write(f"建議口數: **{atk_lots} 口**")
                                st.write(f"預估成本: ${atk_cost:,.0f}")
                                st.caption(f"保留資金: ${total_capital - atk_cost:,.0f}")
                        else:
                            st.warning("無報價")
                    
                    # === 策略說明區 ===
                    st.divider()
                    st.markdown("""
                    ### 📖 策略使用說明
                    
                    * **🛡️ 防守模式 (Defense Mode)**
                        * **時機**：當 K 線在 MA5 與 MA20 之間震盪，或您只是想「試單」看方向對不對。
                        * **目的**：**活下去**。控制虧損在總資金的很小比例，即便歸零也不會影響心態。
                        * **計算**：預設僅投入 **5%** 資金。
                    
                    * **⚔️ 攻擊模式 (Attack Mode)**
                        * **時機**：當 K 線明顯突破 (強多) 或 跌破 (強空)，且成交量放大時。
                        * **目的**：**獲利爆發**。利用選擇權的高槓桿特性，在趨勢正確時放大獲利。
                        * **計算**：預設投入 **30%** 資金 (可於左側調整)。
                        * *注意：攻擊模式伴隨高風險，建議嚴格設定停損。*
                    """)

else:
    st.info("👈 請從側邊欄上傳資料並設定資金，以開始分析。")
