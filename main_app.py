import streamlit as st
import pandas as pd
import yfinance as yf
import urllib.request
from io import BytesIO
import re

# =========================
# 1. アプリ設定 & 認証
# =========================
st.set_page_config(page_title="Sniper V3.5 - Elite 10", layout="wide")
MY_PASSWORD = "stock testa"

if "auth" not in st.session_state: st.session_state.auth = False
if "candidates_df" not in st.session_state:
    st.session_state.candidates_df = pd.DataFrame(columns=["コード", "信用買増", "信用売増", "現物差"])

if not st.session_state.auth:
    st.title("🔒 認証")
    pwd = st.text_input("パスワード", type="password")
    if pwd == MY_PASSWORD:
        st.session_state.auth = True
        st.rerun()
    st.stop()

# =========================
# 2. 需給解析エンジン (V3.3準拠)
# =========================
def parse_matsui_paste(text):
    try:
        def to_num(s): return int(re.sub(r'[^\d]', '', s))
        res = {"買残": 0, "売残": 0, "現物": 0}
        p = re.search(r'([\d,]+)株\s*(買越し|売越し)', text)
        if p: res["現物"] = to_num(p.group(1)) * (1 if "買越し" in p.group(2) else -1)
        b = re.search(r'([\d,]+)株\s*(買残増|買残減)', text)
        if b: res["買残"] = to_num(b.group(1)) * (1 if "買残増" in b.group(2) else -1)
        s = re.search(r'([\d,]+)株\s*(売残増|売残減|売残)', text)
        if s: res["売残"] = to_num(s.group(1)) * (-1 if "売残減" in s.group(2) else 1)
        return res if (p or b or s) else None
    except: return None

# =========================
# 3. Step 1: 候補銘柄の自動抽出 (精鋭10銘柄)
# =========================
st.title("🎯 Pre-Market Sniper V3.5")

st.sidebar.subheader("🔍 Step 1: スキャン設定")
market = st.sidebar.radio("市場を選択", ("プライム", "スタンダード", "グロース"))
min_trading_val = st.sidebar.slider("💰 最低売買代金 (億円)", 1, 50, 10)
# デフォルトを10に設定
top_n = st.sidebar.slider("🔥 抽出上限 (RVOL順)", 5, 50, 10)
st.sidebar.markdown("---")

if st.sidebar.button("スクリーニング開始", type="primary"):
    with st.spinner("精鋭銘柄を抽出中..."):
        try:
            with urllib.request.urlopen("https://raw.githubusercontent.com/watarai0202-netizen/stocktest-app-1/main/data_j.csv") as resp:
                master = pd.read_csv(BytesIO(resp.read()))
            m_key = f"{market}（内国株式）"
            tickers = [f"{str(c).strip().replace('.0','')}.T" for c in master[master["市場・商品区分"] == m_key]["コード"]]
            
            candidate_list = []
            status_area = st.empty()
            for i in range(0, len(tickers), 50):
                batch = tickers[i:i+50]
                status_area.text(f"スキャン中... {i}/{len(tickers)}")
                df_p = yf.download(batch, period="1mo", interval="1d", group_by="ticker", progress=False)
                for t in batch:
                    try:
                        data = df_p[t].dropna()
                        if len(data) < 15: continue
                        vol_y = data["Volume"].iloc[-1]
                        avg_vol = data["Volume"].iloc[-6:-1].mean()
                        rvol = vol_y / avg_vol
                        close_y = data["Close"].iloc[-1]
                        hi_10d = data["High"].iloc[-11:-1].max()
                        t_value_oku = (close_y * vol_y) / 1e8
                        
                        # RVOL(1.15-1.6) & 10日高値超え & 売買代金10億以上
                        if 1.15 <= rvol <= 1.6 and close_y >= hi_10d and t_value_oku >= min_trading_val:
                            candidate_list.append({"コード": t.replace(".T", ""), "rvol": rvol})
                    except: continue
            
            status_area.empty()
            # RVOL（勢い）順にソートして上位10銘柄を抽出
            sorted_f = sorted(candidate_list, key=lambda x: x["rvol"], reverse=True)[:top_n]
            st.session_state.candidates_df = pd.DataFrame([{"コード": c["コード"], "信用買増": 0, "信用売増": 0, "現物差": 0} for c in sorted_f])
            st.success(f"期待値の高い {len(sorted_f)} 銘柄を厳選しました。")
        except Exception as e: st.error(f"エラー: {e}")

# =========================
# 4. Step 2: 需給データの入力 (V3.3準拠)
# =========================
st.subheader("📝 Step 2: 需給コピペ入力")
if not st.session_state.candidates_df.empty:
    col_input, col_table = st.columns([1, 2])
    with col_input:
        target_code = st.selectbox("対象コードを選択", st.session_state.candidates_df["コード"])
        paste_area = st.text_area("松井のテキストをペースト", height=150)
        if st.button("反映する"):
            parsed = parse_matsui_paste(paste_area)
            if parsed:
                idx = st.session_state.candidates_df[st.session_state.candidates_df["コード"] == target_code].index
                st.session_state.candidates_df.loc[idx, ["信用買増", "信用売増", "現物差"]] = [parsed["買残"], parsed["売残"], parsed["現物"]]
                if "editor" in st.session_state: del st.session_state["editor"]
                st.rerun()
            else: st.error("解析できません。")
    with col_table:
        edited_df = st.data_editor(st.session_state.candidates_df, use_container_width=True, key="editor")

# =========================
# 5. Step 3: 指値算出
# =========================
if st.button("🚀 Step 3: 指値算出", type="secondary"):
    if edited_df.empty: st.warning("候補がありません。")
    else:
        # 先物トレンド取得
        try:
            df_f = yf.download("NIY=F", period="1d", interval="5m", progress=False)
            h, l, c = df_f['High'].max(), df_f['Low'].min(), df_f['Close'].iloc[-1]
            f_rate = (c - l) / (h - l) if (h - l) > 0 else 0
            f_adj = 1.0 if f_rate >= 0.6 else 0.985 if f_rate <= 0.3 else 0.995
            st.info(f"**先物判定:** {'🔥V字' if f_rate >= 0.6 else '⚠️L字' if f_rate <= 0.3 else '⚖️通常'} (戻し率: {f_rate:.1%})")
        except: f_adj = 1.0; st.warning("先物取得不可")

        # 最終判定
        t_ticks = [f"{c}.T" for c in edited_df["コード"]]
        df_final = yf.download(t_ticks, period="5d", interval="1d", group_by="ticker", progress=False)
        final = []
        for _, row in edited_df.iterrows():
            t = f"{row['コード']}.T"
            if t not in df_final.columns.levels[0]: continue
            ma5 = df_final[t]["Close"].dropna().tail(5).mean()
            # 需給スコアリング
            score = (15 if row['信用売増'] > row['信用買増'] else 0) + (5 if row['現物差'] > 0 else 0) - (15 if row['信用買増'] > 50000 else 0)
            final.append({
                "コード": row['コード'], "5MA": f"{ma5:,.0f}", "理想指値": f"{ma5 * f_adj:,.0f}", 
                "判定": "🎯狙撃" if score >= 15 else "慎重"
            })
        st.table(pd.DataFrame(final))
