import streamlit as st
import pandas as pd
import yfinance as yf
import urllib.request
from io import BytesIO
import re

# =========================
# 1. API & セキュリティ設定
# =========================
st.set_page_config(page_title="Sniper V5.6 - Stable", layout="wide")

try:
    # Secretsから認証とAPI URLを取得
    MY_PASSWORD = st.secrets["general"]["password"]
    MASTER_API = st.secrets["general"]["master_url"]
    MARGIN_API = st.secrets["general"]["margin_url"]
except KeyError as e:
    st.error(f"Secretsの設定が不足しています: {e}")
    st.info("管理画面で password, master_url, margin_url を設定してください。")
    st.stop()

# 認証ロジック
if "auth" not in st.session_state: st.session_state.auth = False
if not st.session_state.auth:
    st.title("🔒 認証")
    pwd = st.text_input("パスワードを入力", type="password")
    if pwd == MY_PASSWORD:
        st.session_state.auth = True
        st.rerun()
    st.stop()

# セッション状態の初期化
if "candidates_df" not in st.session_state:
    st.session_state.candidates_df = pd.DataFrame(columns=["コード", "信用買増", "信用売増", "現物差"])
if "price_cache" not in st.session_state:
    st.session_state.price_cache = {}

# =========================
# 2. 外部API連携関数
# =========================
def call_github_api(url):
    try:
        req = urllib.request.Request(url)
        req.add_header('Cache-Control', 'no-cache') # キャッシュ回避
        with urllib.request.urlopen(req) as resp:
            return pd.read_csv(BytesIO(resp.read()))
    except: return pd.DataFrame()

def parse_matsui_text(text):
    """手動入力解析"""
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
# 3. Step 1: 市場スキャン (Yahoo Finance API)
# =========================
st.title("🎯 Pre-Market Sniper V5.6")

st.sidebar.subheader("📡 Step 1")
market = st.sidebar.radio("市場選択", ("プライム", "スタンダード", "グロース"))

if st.sidebar.button("スキャン実行", type="primary"):
    with st.spinner("スキャン中..."):
        master = call_github_api(MASTER_API)
        if not master.empty:
            m_key = f"{market}（内国株式）"
            tickers = [f"{str(c).strip().replace('.0','')}.T" for c in master[master["市場・商品区分"] == m_key]["コード"]]
            found = []
            # 100銘柄ずつのバッチ処理
            for i in range(0, len(tickers), 100):
                batch = tickers[i:i+100]
                df_p = yf.download(batch, period="1mo", interval="1d", group_by="ticker", progress=False)
                for t in batch:
                    try:
                        data = df_p[t].dropna()
                        if len(data) < 15: continue
                        v_y = data["Volume"].iloc[-1]
                        rvol = v_y / data["Volume"].iloc[-6:-1].mean()
                        if 1.15 <= rvol <= 1.6 and data["Close"].iloc[-1] >= data["High"].iloc[-11:-1].max():
                            code = t.replace(".T", "")
                            found.append({"コード": code, "rvol": rvol})
                            # メモリに5MAを保持
                            st.session_state.price_cache[code] = data["Close"].tail(5).mean()
                    except: continue
            sorted_f = sorted(found, key=lambda x: x["rvol"], reverse=True)[:10]
            st.session_state.candidates_df = pd.DataFrame([{"コード": c["コード"], "信用買増": 0, "信用売増": 0, "現物差": 0} for c in sorted_f])
            st.success("スキャン完了。")

# =========================
# 4. Step 2: 需給データの同期
# =========================
st.subheader("📝 Step 2: 需給データの同期")
c1, c2 = st.columns([1, 1])
with c1:
    if st.button("🌐 GitHub同期 (margin_data.csv)", type="secondary"):
        margin_df = call_github_api(MARGIN_API)
        if not margin_df.empty:
            for idx, row in st.session_state.candidates_df.iterrows():
                match = margin_df[margin_df["コード"].astype(str) == str(row["コード"])]
                if not match.empty:
                    st.session_state.candidates_df.loc[idx, ["信用買増", "信用売増", "現物差"]] = [
                        match.iloc[0].get("信用買増", 0), match.iloc[0].get("信用売増", 0), match.iloc[0].get("現物差", 0)
                    ]
            if "editor" in st.session_state: del st.session_state["editor"]
            st.rerun()

with c2:
    with st.form("manual_form", clear_on_submit=True):
        t_code = st.selectbox("個別入力", st.session_state.candidates_df["コード"])
        p_text = st.text_area("コピペエリア")
        if st.form_submit_button("反映"):
            res = parse_matsui_text(p_text)
            if res:
                idx = st.session_state.candidates_df[st.session_state.candidates_df["コード"] == t_code].index
                st.session_state.candidates_df.loc[idx, ["信用買増", "信用売増", "現物差"]] = [res["買残"], res["売残"], res["現物"]]
                if "editor" in st.session_state: del st.session_state["editor"]
                st.rerun()

edited_df = st.data_editor(st.session_state.candidates_df, use_container_width=True, key="editor")

# =========================
# 5. Step 3: 指値算出 (API耐性強化)
# =========================
if st.button("🚀 Step 3: 指値算出"):
    if not edited_df.empty:
        # 先物調整ロジック
        f_adj = 1.0 
        try:
            # 安定のため2日分を取得
            df_f = yf.download("NIY=F", period="2d", interval="5m", progress=False)
            if not df_f.empty:
                h, l, c = df_f['High'].max(), df_f['Low'].min(), df_f['Close'].iloc[-1]
                f_rate = (c - l) / (h - l) if (h - l) > 0 else 0.5
                f_adj = 1.0 if f_rate >= 0.6 else 0.985 if f_rate <= 0.3 else 0.995
                st.info(f"先物状況を確認しました (戻し率: {f_rate:.1%})")
            else:
                st.warning("先物データ未取得。倍率1.0で続行します。")
        except:
            st.warning("先物APIエラー。倍率1.0で続行します。")
        
        # 最終判定
        final = []
        for _, row in edited_df.iterrows():
            ma5 = st.session_state.price_cache.get(row['コード'], 0)
            score = (15 if row['信用売増'] > row['信用買増'] else 0) + (5 if row['現物差'] > 0 else 0) - (15 if row['信用買増'] > 50000 else 0)
            final.append({
                "コード": row['コード'], "5MA": f"{ma5:,.0f}", "需給スコア": score, 
                "狙撃指値": f"{ma5 * f_adj:,.0f}", "判定": "🎯狙撃" if score >= 15 else "慎重"
            })
        st.table(pd.DataFrame(final))
