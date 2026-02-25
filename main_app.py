import streamlit as st
import pandas as pd
import yfinance as yf
import urllib.request
from io import BytesIO
import re

# =========================
# 1. アプリ設定 & 認証
# =========================
st.set_page_config(page_title="Sniper V5.0 - Ultimate", layout="wide")
MY_PASSWORD = "stock testa"

# セッション状態の初期化
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
# 2. エラー回避型 データ読み込み
# =========================
@st.cache_data(ttl=3600)
def load_master():
    try:
        url = "https://raw.githubusercontent.com/watarai0202-netizen/stocktest-app-1/main/data_j.csv"
        with urllib.request.urlopen(url) as resp:
            content = resp.read()
            if not content: return pd.DataFrame() # 空なら空のDFを返す
            return pd.read_csv(BytesIO(content))
    except Exception:
        return pd.DataFrame()

def parse_matsui_paste(text):
    """画像内のコピペ形式に対応した解析"""
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
# 3. Step 1: 精鋭抽出 (通信の塊)
# =========================
st.title("🎯 Pre-Market Sniper V5.0")

st.sidebar.subheader("🔍 Step 1: スキャン")
market = st.sidebar.radio("市場", ("プライム", "スタンダード", "グロース"))
min_v = st.sidebar.slider("最低売買代金(億)", 1, 50, 10)

if st.sidebar.button("スキャン実行"):
    with st.spinner("データ取得中..."):
        master = load_master()
        if master.empty:
            st.error("マスターデータが読み込めません。GitHubのURLを確認してください。")
        else:
            m_key = f"{market}（内国株式）"
            tickers = [f"{str(c).strip().replace('.0','')}.T" for c in master[master["市場・商品区分"] == m_key]["コード"]]
            
            found = []
            # バッチ処理で通信を高速化
            for i in range(0, len(tickers), 100):
                batch = tickers[i:i+100]
                df_p = yf.download(batch, period="1mo", interval="1d", group_by="ticker", progress=False)
                for t in batch:
                    try:
                        data = df_p[t].dropna()
                        if len(data) < 15: continue
                        v_y = data["Volume"].iloc[-1]
                        rvol = v_y / data["Volume"].iloc[-6:-1].mean()
                        close_y = data["Close"].iloc[-1]
                        if 1.15 <= rvol <= 1.6 and close_y >= data["High"].iloc[-11:-1].max() and (close_y * v_y / 1e8) >= min_v:
                            code = t.replace(".T", "")
                            found.append({"コード": code, "rvol": rvol})
                            # メモリに5MAを保存して再起動対策
                            st.session_state.price_cache[code] = data["Close"].tail(5).mean()
                    except: continue
            
            sorted_f = sorted(found, key=lambda x: x["rvol"], reverse=True)[:10]
            st.session_state.candidates_df = pd.DataFrame([{"コード": c["コード"], "信用買増": 0, "信用売増": 0, "現物差": 0} for c in sorted_f])
            st.success("10銘柄を厳選しました。")

# =========================
# 4. Step 2: 需給入力 (入力中は何もしない設計)
# =========================
st.subheader("📝 Step 2: 需給コピペ入力")
if not st.session_state.candidates_df.empty:
    c1, c2 = st.columns([1, 2])
    with c1:
        # 入力フォーム化して、1回ごとにアプリが止まるのを防ぐ
        with st.form("paste_form"):
            target_code = st.selectbox("対象コード", st.session_state.candidates_df["コード"])
            paste_area = st.text_area("松井証券のテキストをペースト", height=100)
            submitted = st.form_submit_button("反映")
            
            if submitted:
                parsed = parse_matsui_paste(paste_area)
                if parsed:
                    idx = st.session_state.candidates_df[st.session_state.candidates_df["コード"] == target_code].index
                    st.session_state.candidates_df.loc[idx, ["信用買増", "信用売増", "現物差"]] = [parsed["買残"], parsed["売残"], parsed["現物"]]
                    if "editor" in st.session_state: del st.session_state["editor"]
                    st.rerun()
                else:
                    st.error("解析不能")
    with c2:
        # data_editorも表示専用に近い形にして負荷を軽減
        edited_df = st.data_editor(st.session_state.candidates_df, use_container_width=True, key="editor")

# =========================
# 5. Step 3: 即時計算
# =========================
if st.button("🚀 Step 3: 指値算出"):
    if edited_df.empty:
        st.warning("候補なし")
    else:
        with st.spinner("先物チェック中..."):
            try:
                # 通信は先物のみ
                df_f = yf.download("NIY=F", period="1d", interval="5m", progress=False)
                f_rate = (df_f['Close'].iloc[-1] - df_f['Low'].min()) / (df_f['High'].max() - df_f['Low'].min())
                f_adj = 1.0 if f_rate >= 0.6 else 0.985 if f_rate <= 0.3 else 0.995
                st.info(f"先物戻し率: {f_rate:.1%}")
            except: f_adj = 1.0
        
        final = []
        for _, row in edited_df.iterrows():
            code = row['コード']
            ma5 = st.session_state.price_cache.get(code, 0)
            # 需給スコア
            score = (15 if row['信用売増'] > row['信用買増'] else 0) + (5 if row['現物差'] > 0 else 0) - (15 if row['信用買増'] > 50000 else 0)
            final.append({
                "コード": code, "5MA": f"{ma5:,.0f}", "需給スコア": score, 
                "指値": f"{ma5 * f_adj:,.0f}", "判定": "🎯狙撃" if score >= 15 else "慎重"
            })
        st.table(pd.DataFrame(final))
