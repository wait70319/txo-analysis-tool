import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import numpy as np
import io
from datetime import datetime

st.set_page_config(page_title="台指選專業點位戰法 v2.5", layout="wide", page_icon="⚔️")

st.title("⚔️ 台指選擇權買方 - 專業攻守點位系統 v2.5")
st.caption("✅ 歷史回測已改成『真實逐筆前瞻模擬』，結果更接近現實")

# ====================== 技術指標 ======================
def calculate_atr(df, period=14):
    high_low = df['最高價'] - df['最低價']
    high_close = np.abs(df['最高價'] - df['收盤價'].shift())
    low_close = np.abs(df['最低價'] - df['收盤價'].shift())
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return tr.rolling(window=period).mean()

def calculate_rsi(df, period=14):
    delta = df['收盤價'].diff()
    gain = delta.where(delta > 0, 0).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def calculate_macd(df, fast=12, slow=26, signal=9):
    ema_fast = df['收盤價'].ewm(span=fast, adjust=False).mean()
    ema_slow = df['收盤價'].ewm(span=slow, adjust=False).mean()
    macd = ema_fast - ema_slow
    signal_line = macd.ewm(span=signal, adjust=False).mean()
    return macd, signal_line

# ====================== 側邊欄 ======================
st.sidebar.header("⚙️ 參數設定")
direction = st.sidebar.radio("目前操作方向", ["看漲 (Buy Call)", "看跌 (Buy Put)"], horizontal=True)
is_bull = "Call" in direction

with st.sidebar.expander("🛡️ 防守設定", expanded=True):
    stop_modes = ["昨日低點/高點 (激進)", "MA5", "MA20", "ATR 動態", "自訂點數"]
    stop_mode = st.selectbox("防守點位依據", stop_modes)
    atr_multiplier = st.slider("ATR 倍數", 0.8, 3.0, 1.5, 0.1) if stop_mode == "ATR 動態" else 1.5
    custom_stop_pts = st.number_input("停損點數", 80, step=10) if stop_mode == "自訂點數" else 80

with st.sidebar.expander("🚀 攻擊設定", expanded=True):
    add_on_layers = st.slider("金字塔加碼層數", 1, 3, 2)
    add_on_ratios = [1.0, 1.8, 2.5][:add_on_layers]

with st.sidebar.expander("📉 趨勢過濾", expanded=True):
    use_trend_filter = st.checkbox("啟用 RSI + MACD 趨勢過濾", True)
    rsi_threshold = st.slider("RSI 中性門檻", 40, 60, 50)

with st.sidebar.expander("💰 資金設定", expanded=True):
    total_capital = st.number_input("總資金 (NT$)", 500000, step=50000)
    risk_per_trade = st.slider("每筆風險 (%)", 0.5, 3.0, 1.0, 0.1) / 100
    backtest_days = st.slider("歷史回測天數", 20, 120, 60)

st.sidebar.markdown("---")
kline_file = st.sidebar.file_uploader("上傳加權指數 K 線", type=['csv', 'xlsx'])
option_file = st.sidebar.file_uploader("上傳選擇權報價", type=['csv', 'xlsx'])

# ====================== 完整資料載入函數 ======================
@st.cache_data
def load_data(k_file, op_file):
    if not k_file or not op_file:
        return None, None
    try:
        # K線 - 自動欄位對應
        if k_file.name.endswith('.csv'):
            df_k = pd.read_csv(k_file)
        else:
            df_k = pd.read_excel(k_file)
        df_k.columns = [str(c).strip() for c in df_k.columns]

        col_map = {
            '時間': 'Date', '日期': 'Date', 'date': 'Date',
            '收盤': '收盤價', 'close': '收盤價',
            '開盤': '開盤價', 'open': '開盤價',
            '最高': '最高價', 'high': '最高價',
            '最低': '最低價', 'low': '最低價',
            'volume': '成交量', 'vol': '成交量'
        }
        df_k = df_k.rename(columns=col_map)

        if 'Date' in df_k.columns:
            df_k['Date'] = pd.to_datetime(df_k['Date'], errors='coerce')
        df_k = df_k.sort_values('Date').reset_index(drop=True)

        numeric_cols = ['收盤價', '開盤價', '最高價', '最低價', '成交量', 'SMA5', 'SMA20']
        for col in numeric_cols:
            if col in df_k.columns:
                df_k[col] = pd.to_numeric(df_k[col], errors='coerce')

        df_k['ATR'] = calculate_atr(df_k)
        df_k['RSI'] = calculate_rsi(df_k)
        df_k['MACD'], df_k['MACD_Signal'] = calculate_macd(df_k)

        # 選擇權
        if op_file.name.lower().endswith('.csv'):
            try:
                df_op = pd.read_csv(op_file, encoding='utf-8')
            except Exception:
                df_op = pd.read_csv(op_file, encoding='big5')
        else:
            df_op = pd.read_excel(op_file)
        df_op.columns = [str(c).strip() for c in df_op.columns]
        if '成交' in df_op.columns:
            df_op['成交'] = pd.to_numeric(df_op['成交'], errors='coerce')
            df_op = df_op.dropna(subset=['成交'])

        def parse_row(row_str):
            try:
                parts = str(row_str).split()
                strike_list = [int(p) for p in parts if p.isdigit() and int(p) > 10000]
                strike = strike_list[0] if strike_list else None
                type_ = 'Call' if any(x in parts for x in ['C', 'Call']) else ('Put' if any(x in parts for x in ['P', 'Put']) else None)
                return type_, strike
            except Exception:
                return None, None

        parse_success = False
        if '商品' in df_op.columns:
            parsed = df_op['商品'].apply(parse_row)
            df_op['Type'] = parsed.apply(lambda x: x[0])
            df_op['Strike'] = parsed.apply(lambda x: x[1])
            valid_count = df_op['Strike'].notna().sum()
            if valid_count == 0:
                st.warning("⚠️ 選擇權欄位解析失敗：找不到履約價。請確認「商品」欄位格式包含如 'TXO22000C' 或 'Call 22000' 等資訊。")
            else:
                parse_success = True
        else:
            st.warning("⚠️ 選擇權檔案中找不到「商品」欄位，無法進行選擇權試算。")

        return df_k, df_op
    except Exception as e:
        st.error(f"資料讀取錯誤: {e}")
        return None, None


df_k, df_op = load_data(kline_file, option_file)

# ====================== 主程式 ======================
if df_k is not None and len(df_k) > 30:
    last_k = df_k.iloc[-1]
    prev_k = df_k.iloc[-2]
    current_price = float(last_k['收盤價'])

    # ---- 防守點計算 ----
    if stop_mode == "ATR 動態":
        atr_val = float(last_k['ATR']) if not np.isnan(last_k['ATR']) else current_price * 0.01
        stop_price = current_price - atr_val * atr_multiplier if is_bull else current_price + atr_val * atr_multiplier
    elif stop_mode == "MA5":
        stop_price = float(last_k['SMA5']) if 'SMA5' in last_k and not np.isnan(last_k['SMA5']) else current_price * 0.99
    elif stop_mode == "MA20":
        stop_price = float(last_k['SMA20']) if 'SMA20' in last_k and not np.isnan(last_k['SMA20']) else current_price * 0.98
    elif stop_mode == "自訂點數":
        stop_price = current_price - custom_stop_pts if is_bull else current_price + custom_stop_pts
    else:
        stop_price = float(prev_k['最低價']) if is_bull else float(prev_k['最高價'])

    risk_dist = abs(current_price - stop_price)
    if risk_dist == 0:
        risk_dist = current_price * 0.01  # 防止除以零

    add_on_prices = [current_price + risk_dist * r * (1 if is_bull else -1) for r in add_on_ratios]

    # ---- 趨勢過濾 ----
    trend_ok = True
    if use_trend_filter:
        last_rsi = float(last_k['RSI']) if not np.isnan(last_k['RSI']) else 50
        macd_val = float(last_k['MACD']) if not np.isnan(last_k['MACD']) else 0
        macd_sig = float(last_k['MACD_Signal']) if not np.isnan(last_k['MACD_Signal']) else 0
        macd_bull = macd_val > macd_sig
        if is_bull:
            trend_ok = last_rsi > rsi_threshold and macd_bull
        else:
            trend_ok = last_rsi < rsi_threshold and not macd_bull

    # ---- 主圖表 ----
    main_fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.7, 0.3]
    )

    main_fig.add_trace(go.Candlestick(
        x=df_k['Date'],
        open=df_k['開盤價'],
        high=df_k['最高價'],
        low=df_k['最低價'],
        close=df_k['收盤價'],
        name='K線'
    ), row=1, col=1)

    if 'SMA5' in df_k.columns:
        main_fig.add_trace(go.Scatter(x=df_k['Date'], y=df_k['SMA5'], name='MA5', line=dict(color='orange')), row=1, col=1)
    if 'SMA20' in df_k.columns:
        main_fig.add_trace(go.Scatter(x=df_k['Date'], y=df_k['SMA20'], name='MA20', line=dict(color='blue')), row=1, col=1)

    # 攻守線延伸至整個 x 軸範圍
    x_start = df_k['Date'].iloc[0]
    x_end = df_k['Date'].iloc[-1]

    # 防守線
    main_fig.add_shape(
        type="line", x0=x_start, x1=x_end, y0=stop_price, y1=stop_price,
        line=dict(color="red", width=2, dash="dash"), row=1, col=1
    )
    main_fig.add_annotation(
        x=x_end, y=stop_price,
        text=f"🛡️ 防守 {stop_price:,.0f}",
        showarrow=False, xanchor="right",
        bgcolor="rgba(255,0,0,0.2)", font=dict(color="red"),
        row=1, col=1
    )

    # 加碼線
    colors = ['gold', 'orange', 'darkorange']
    for i, price in enumerate(add_on_prices):
        main_fig.add_shape(
            type="line", x0=x_start, x1=x_end, y0=price, y1=price,
            line=dict(color=colors[i], width=2), row=1, col=1
        )
        main_fig.add_annotation(
            x=x_end, y=price,
            text=f"🚀 加碼{i+1} {price:,.0f}",
            showarrow=False, xanchor="right",
            yshift=(i + 1) * 12,  # 避免標籤重疊
            bgcolor="rgba(255,215,0,0.2)", font=dict(color="darkorange"),
            row=1, col=1
        )

    # ---- 成交量子圖（修正 Bug）----
    if '成交量' in df_k.columns:
        vol_series = pd.to_numeric(df_k['成交量'], errors='coerce').fillna(0)
    else:
        vol_series = pd.Series([0] * len(df_k))

    main_fig.add_trace(go.Bar(
        x=df_k['Date'],
        y=vol_series,
        name='成交量',
        marker_color='rgba(120,120,120,0.6)'
    ), row=2, col=1)

    main_fig.update_layout(
        height=750,
        title_text="K線圖 + 攻守點位 + 成交量",
        xaxis_rangeslider_visible=False,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )
    main_fig.update_yaxes(title_text="指數", row=1, col=1)
    main_fig.update_yaxes(title_text="成交量", row=2, col=1)

    st.session_state['main_fig'] = main_fig
    st.session_state['current_price'] = current_price
    st.session_state['stop_price'] = stop_price
    st.session_state['risk_dist'] = risk_dist

    tab1, tab2, tab3, tab4 = st.tabs(["📊 當前戰情", "📈 歷史回測", "💰 資金曲線", "📄 PDF交易計畫"])

    # ==================== Tab1：當前戰情 ====================
    with tab1:
        st.plotly_chart(main_fig, use_container_width=True)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("📍 進場價", f"{current_price:,.0f}")
        c2.metric("🛡️ 防守點", f"{stop_price:,.0f}", f"-{risk_dist:,.0f}點")
        c3.metric("🚀 第1層攻擊", f"{add_on_prices[0]:,.0f}", f"+{abs(add_on_prices[0]-current_price):,.0f}點")
        c4.metric("趨勢過濾", "✅通過" if trend_ok else "❌不建議")

        if not trend_ok:
            st.error("⚠️ 趨勢過濾不通過，建議暫緩或減量")

        st.subheader("💰 選擇權實戰資金試算")
        if df_op is not None and 'Strike' in df_op.columns and 'Type' in df_op.columns:
            valid_strikes = df_op['Strike'].dropna()
            if len(valid_strikes) > 0:
                strikes = sorted(valid_strikes.unique())
                atm_strike = min(strikes, key=lambda x: abs(x - current_price))
                op_type = 'Call' if is_bull else 'Put'
                target = df_op[(df_op['Strike'] == atm_strike) & (df_op['Type'] == op_type)]
                if not target.empty:
                    op_price = target.iloc[0]['成交']
                    lot_cost = op_price * 50
                    est_loss = risk_dist * 0.5 * 50
                    colA, colB = st.columns(2)
                    colA.metric("🎯 ATM合約", f"{op_type} {atm_strike}", f"報價 {op_price}")
                    colB.metric("單口成本", f"NT$ {lot_cost:,.0f}")
                    st.warning(f"⚠️ 若觸及防守點，預估每口虧損 ≈ NT$ {est_loss:,.0f}")
                else:
                    st.info(f"找不到 {op_type} {atm_strike} 的報價資料")
            else:
                st.info("選擇權資料中無有效履約價，無法進行試算")

    # ==================== Tab2：歷史回測（修正 risk_dist Bug）====================
    with tab2:
        st.subheader("📈 歷史點位回測（真實逐筆前瞻模擬）")
        st.caption("每筆進場獨立計算當時的風險距，並判斷未來最多 10 天內是否先觸及防守或攻擊")
        if use_trend_filter:
            st.info("ℹ️ 回測已同步套用 RSI + MACD 趨勢過濾條件")

        if st.button("🚀 開始執行歷史回測", type="primary"):
            with st.spinner(f"正在模擬過去 {backtest_days} 天真實走勢..."):
                results = []
                max_horizon = 10
                skipped = 0

                for i in range(max(0, len(df_k) - backtest_days), len(df_k) - max_horizon):
                    row_i = df_k.iloc[i]
                    entry_p = float(row_i['收盤價'])

                    # ---- 趨勢過濾（同步套用）----
                    if use_trend_filter:
                        rsi_i = float(row_i['RSI']) if not np.isnan(row_i['RSI']) else 50
                        macd_i = float(row_i['MACD']) if not np.isnan(row_i['MACD']) else 0
                        sig_i = float(row_i['MACD_Signal']) if not np.isnan(row_i['MACD_Signal']) else 0
                        bull_ok = rsi_i > rsi_threshold and macd_i > sig_i
                        bear_ok = rsi_i < rsi_threshold and macd_i < sig_i
                        if is_bull and not bull_ok:
                            skipped += 1
                            continue
                        if not is_bull and not bear_ok:
                            skipped += 1
                            continue

                    # ---- 當筆防守點（用當時 K 棒資料計算，修正原 Bug）----
                    if stop_mode == "ATR 動態":
                        atr_i = float(row_i['ATR']) if not np.isnan(row_i['ATR']) else entry_p * 0.01
                        stop_p = entry_p - atr_i * atr_multiplier if is_bull else entry_p + atr_i * atr_multiplier
                    elif stop_mode == "MA5":
                        sma5_i = float(row_i['SMA5']) if 'SMA5' in row_i and not np.isnan(row_i['SMA5']) else entry_p * 0.99
                        stop_p = sma5_i
                    elif stop_mode == "MA20":
                        sma20_i = float(row_i['SMA20']) if 'SMA20' in row_i and not np.isnan(row_i['SMA20']) else entry_p * 0.98
                        stop_p = sma20_i
                    elif stop_mode == "自訂點數":
                        stop_p = entry_p - custom_stop_pts if is_bull else entry_p + custom_stop_pts
                    else:
                        prev_row = df_k.iloc[i - 1] if i > 0 else row_i
                        stop_p = float(prev_row['最低價']) if is_bull else float(prev_row['最高價'])

                    # ---- 當筆風險距（修正原本沿用即時 risk_dist 的 Bug）----
                    rd_i = abs(entry_p - stop_p)
                    if rd_i == 0:
                        rd_i = entry_p * 0.01

                    add_on_p = entry_p + rd_i * add_on_ratios[0] * (1 if is_bull else -1)

                    future = df_k.iloc[i + 1: i + 1 + max_horizon]
                    hit_stop = False
                    hit_addon = False

                    for _, frow in future.iterrows():
                        high = float(frow['最高價'])
                        low = float(frow['最低價'])
                        if is_bull:
                            if low <= stop_p:
                                hit_stop = True
                                break
                            if high >= add_on_p:
                                hit_addon = True
                                break
                        else:
                            if high >= stop_p:
                                hit_stop = True
                                break
                            if low <= add_on_p:
                                hit_addon = True
                                break

                    if hit_stop:
                        pnl_r = -1.0
                    elif hit_addon:
                        pnl_r = add_on_ratios[0]
                    else:
                        final_p = float(future.iloc[-1]['收盤價'])
                        pnl_r = (final_p - entry_p) / rd_i * (1 if is_bull else -1)

                    results.append({'pnl_r': pnl_r, 'rd': rd_i, 'entry': entry_p})

                if results:
                    pnl_rs = [r['pnl_r'] for r in results]
                    win_rate = len([x for x in pnl_rs if x > 0]) / len(pnl_rs) * 100
                    avg_r = np.mean(pnl_rs)
                    total_r = sum(pnl_rs)
                    max_dd = 0
                    cumulative = 0
                    peak = 0
                    for r in pnl_rs:
                        cumulative += r
                        peak = max(peak, cumulative)
                        max_dd = min(max_dd, cumulative - peak)

                    col_a, col_b, col_c, col_d, col_e = st.columns(5)
                    col_a.metric("勝率", f"{win_rate:.1f}%")
                    col_b.metric("平均報酬", f"{avg_r:.2f}R")
                    col_c.metric("總報酬", f"{total_r:.1f}R")
                    col_d.metric("最大回撤", f"{max_dd:.1f}R")
                    col_e.metric("有效樣本", f"{len(results)} 筆（過濾 {skipped} 筆）")

                    # 資金曲線用各筆實際 rd 計算
                    equity = [total_capital]
                    for r in results:
                        risk_amount = equity[-1] * risk_per_trade
                        contracts = max(1, int(risk_amount / (r['rd'] * 50)))
                        trade_pnl = r['pnl_r'] * r['rd'] * 50 * contracts
                        equity.append(equity[-1] + trade_pnl)

                    eq_df = pd.DataFrame({"交易次數": range(len(equity)), "資金 (NT$)": equity})
                    st.line_chart(eq_df.set_index("交易次數")["資金 (NT$)"], use_container_width=True)
                    st.success(f"最終資金：**NT$ {equity[-1]:,.0f}**　｜　總報酬 **{(equity[-1]/total_capital-1)*100:+.1f}%**")
                else:
                    st.warning("沒有符合條件的回測樣本，請調整趨勢過濾條件或增加回測天數")

    # ==================== Tab3：蒙地卡羅資金曲線 ====================
    with tab3:
        st.subheader("💰 蒙地卡羅資金曲線模擬")
        st.warning("⚠️ 此頁為統計模擬，非真實回測。勝率與報酬倍數為假設值，不代表實際績效。")
        col_mc1, col_mc2 = st.columns(2)
        with col_mc1:
            sim_trades = st.slider("模擬交易次數", 10, 200, 80)
            sim_win_rate = st.slider("假設勝率 (%)", 30, 70, 52) / 100
        with col_mc2:
            sim_rr = st.slider("假設獲利倍數 (R)", 1.0, 4.0, 1.45, 0.05)
            sim_seed = st.number_input("隨機種子（固定結果用）", 0, 9999, 42)

        if st.button("產生資金曲線", type="primary"):
            np.random.seed(int(sim_seed))
            wins = np.random.rand(sim_trades) < sim_win_rate
            pnls = np.where(wins, risk_dist * sim_rr, -risk_dist)
            equity = [total_capital]
            for pnl_points in pnls:
                risk_amount = equity[-1] * risk_per_trade
                contracts = max(1, int(risk_amount / (risk_dist * 50)))
                trade_pnl = pnl_points * 50 * contracts
                equity.append(equity[-1] + trade_pnl)
            eq_df = pd.DataFrame({"交易次數": range(len(equity)), "資金 (NT$)": equity})
            st.line_chart(eq_df.set_index("交易次數")["資金 (NT$)"], use_container_width=True)
            st.success(f"最終資金：**NT$ {equity[-1]:,.0f}**　｜　總報酬 **{(equity[-1]/total_capital-1)*100:+.1f}%**")

    # ==================== Tab4：PDF ====================
    with tab4:
        st.subheader("📄 一鍵匯出完整交易計畫 PDF（含圖表）")
        st.info("💡 需安裝 kaleido：`pip install kaleido`")

        if st.button("📥 生成並下載 PDF", type="primary"):
            if 'main_fig' in st.session_state:
                try:
                    buffer = io.BytesIO()
                    st.session_state['main_fig'].write_image(
                        buffer, format="pdf", engine="kaleido", width=1400, height=900
                    )
                    buffer.seek(0)
                    st.download_button(
                        label="💾 下載 PDF",
                        data=buffer,
                        file_name=f"台指選_攻守計畫_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
                        mime="application/pdf"
                    )
                    st.success("✅ PDF 已生成！")
                except ImportError:
                    st.error("❌ PDF 產生失敗：請先安裝 kaleido（pip install kaleido）")
                except Exception as e:
                    st.error(f"❌ PDF 產生失敗: {e}")
            else:
                st.warning("請先到『當前戰情』頁籤載入圖表後再匯出")

else:
    st.info("👈 請在左側側邊欄上傳 K 線與選擇權報價檔案後開始使用")
    st.markdown("""
    ### 📋 檔案格式說明
    **K 線 CSV/XLSX 必要欄位：**
    - `日期` 或 `時間`（Date）
    - `開盤` / `最高` / `最低` / `收盤`（或英文 open/high/low/close）
    - `成交量`（選填）
    - `SMA5` / `SMA20`（選填，若無則自動略過 MA 線）

    **選擇權報價 CSV/XLSX 必要欄位：**
    - `商品`：需包含履約價與 Call/Put 資訊（如 `TXO22000C` 或 `Call 22000`）
    - `成交`：成交價格
    """)
