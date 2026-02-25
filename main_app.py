import streamlit as st
import pandas as pd
import yfinance as yf
import urllib.request
from io import BytesIO
import re

# =========================
# 1. セキュリティ & 認証
# =========================
st.set_page_config(page_title="Sniper V5.2 - GitHub Sync", layout="wide")

# Secretsから設定を読み込み。見つからない場合はエラーを表示
try:
    MY_PASSWORD = st.secrets["general"]["password"]
    # 銘柄マスタ（東証のリストなど）
    MASTER_CSV_URL = st.secrets["general"].get("master_url", "https://raw.githubusercontent.com/watarai0202-netizen/stocktest-app-1/main/data_j.csv")
    # 需給データ（ユーザー様の margin_data.csv）
    MARGIN_CSV_URL = "https://raw.githubusercontent.com/watarai0202-netizen/snipe-stock/main/data/margin_data.csv"
except KeyError:
    st.error("Secretsに 'password' が設定されていません。")
    st.stop()

if "auth" not in st.session_state: st.session_state.auth = False
if "candidates_df" not in st.session_state:
    st.session_state.candidates_df = pd.DataFrame(columns=["コード", "信用買増", "信用売増", "現物差"])
if "price_cache" not in st.session_state:
    st.session_state.price_cache = {}

if not st.session_state.auth:
    st.title("🔒 認証")
    pwd = st.text_input("パスワード", type="password")
    if pwd == MY_PASSWORD:
        st.session_state.auth = True
        st.rerun()
    st.stop()

# =========================
# 2. データ読み込み関数
# =========================
def fetch_csv_from_github(url):
    """GitHubからCSVを読み込む（エラーハンドリング付き）"""
    try:
        with urllib.request.urlopen(url) as resp:
            content = resp.read()
            if not content: return pd.DataFrame()
            return pd.read_csv(BytesIO(content))
    except Exception as e:
        st.error(f"CSV読み込みエラー: {e}")
        return pd.DataFrame()

# =========================
# 3. Step 1: 精鋭抽出
# =========================
st.title("🎯 Pre-Market Sniper V5.2")

st.sidebar.subheader("🔍 Step 1: スキャン")
market = st.sidebar.radio("市場", ("プライム", "スタンダード", "グロース"))

if st.sidebar.button("スキャン実行", type="primary"):
    with st.spinner("市場データを解析中..."):
        master = fetch_csv_from_github(MASTER_CSV_URL)
        if master.empty:
            st.warning("マスタデータが空です。URLを確認してください。")
        else:
            m_key = f"{market}（内国株式）"
            tickers = [f"{str(c).strip().replace('.0','')}.T" for c in master[master["市場・商品区分"] == m_key]["コード"]]
            
            found = []
            for i in range(0, len(tickers), 100):
                df_p = yf.download(tickers[i:i+100], period="1mo", interval="1d", group_by="ticker", progress=False)
                for t in tickers[i:i+100]:
                    try:
                        data = df_p[t].dropna()
                        if len(data) < 15: continue
                        v_y = data["Volume"].iloc[-1]
                        rvol = v_y / data["Volume"].iloc[-6:-1].mean()
                        close_y = data["Close"].iloc[-1]
                        # スクリーニング条件
                        if 1.15 <= rvol <= 1.6 and close_y >= data["High"].iloc[-11:-1].max():
                            code = t.replace(".T", "")
                            found.append({"コード": code, "rvol": rvol})
                            st.session_state.price_cache[code] = data["Close"].tail(5).mean()
                    except: continue
            
            sorted_f = sorted(found, key=lambda x: x["rvol"], reverse=True)[:10]
            st.session_state.candidates_df = pd.DataFrame([{"コード": c["コード"], "信用買増": 0, "信用売増": 0, "現物差": 0} for c in sorted_f])
            st.success("10銘柄を抽出しました。")

# =========================
# 4. Step 2: 需給データの反映 (自動CSV読み込み)
# =========================
st.subheader("📝 Step 2: 需給データの反映")

col_auto, col_manual = st.columns([1, 1])

with col_auto:
    st.info("💡 GitHubの `margin_data.csv` から一括で読み込みます。")
    if st.button("🌐 GitHubから需給データを同期", type="secondary"):
        with st.spinner("同期中..."):
            margin_df = fetch_csv_from_github(MARGIN_CSV_URL)
            if not margin_df.empty:
                # 抽出した10銘柄に合致するデータだけを上書き
                for idx, row in st.session_state.candidates_df.iterrows():
                    match = margin_df[margin_df["コード"].astype(str) == str(row["コード"])]
                    if not match.empty:
                        st.session_state.candidates_df.loc[idx, ["信用買増", "信用売増", "現物差"]] = [
                            match.iloc[0]["信用買増"], match.iloc[0]["信用売増"], match.iloc[0]["現物差"]
                        ]
                if "editor" in st.session_state: del st.session_state["editor"]
                st.success("GitHubとの同期が完了しました！")
                st.rerun()

with col_manual:
    st.caption("個別入力（コピペ）も可能です。")
    with st.form("paste_form", clear_on_submit=True):
        target_code = st.selectbox("対象コード", st.session_state.candidates_df["コード"])
        paste_area = st.text_area("コピペ用エリア", height=68)
        if st.form_submit_button("反映"):
            # (以前のparse_matsui_paste関数をここに呼び出すロジック)
            pass

edited_df = st.data_editor(st.session_state.candidates_df, use_container_width=True, key="editor")

# =========================
# 5. Step 3: 指値算出
# =========================
if st.button("🚀 Step 3: 指値算出"):
    # (先物取得と5MA計算ロジック)
    st.write("最終計算結果を表示します...")
