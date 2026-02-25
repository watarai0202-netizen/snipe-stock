import streamlit as st
import pandas as pd
import yfinance as yf
import requests
import base64
import json
from io import BytesIO
import re
from datetime import datetime
import urllib.request

# =========================
# 1. 基本設定 & 認証 (Secrets連携)
# =========================
st.set_page_config(page_title="Pre-Market Sniper V5.3", layout="wide")

# パスワードとトークンをSecretsから取得
MY_PASSWORD = st.secrets["MY_APP_PASSWORD"]
GITHUB_TOKEN = st.secrets["GITHUB_TOKEN"]

if "auth" not in st.session_state: st.session_state.auth = False
if "margin_df" not in st.session_state: st.session_state.margin_df = None
if "candidates_df" not in st.session_state: st.session_state.candidates_df = pd.DataFrame()
if "price_cache" not in st.session_state: st.session_state.price_cache = {}

if not st.session_state.auth:
    st.title("🔒 認証")
    pwd = st.text_input("パスワード", type="password")
    if pwd == MY_PASSWORD:
        st.session_state.auth = True
        st.rerun()
    st.stop()

# =========================
# 2. GitHub API 設定
# =========================
# ★ご自身のリポジトリ名に変更してください
REPO = "watarai0202-netizen/snipe-stock" 
FILE_PATH = "data/margin_data.csv"
API_URL = f"https://api.github.com/repos/{REPO}/contents/{FILE_PATH}"

def load_from_github():
    """GitHubから一度だけデータを読み込む"""
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    res = requests.get(API_URL, headers=headers)
    if res.status_code == 200:
        content = base64.b64decode(res.json()["content"]).decode('utf-8')
        return pd.read_csv(BytesIO(content.encode('utf-8')))
    return pd.DataFrame(columns=["コード", "信用買増", "信用売増", "現物差", "更新日"])

def save_to_github(df):
    """GitHubへ一括保存する"""
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    res = requests.get(API_URL, headers=headers)
    sha = res.json()["sha"] if res.status_code == 200 else None
    csv_content = df.to_csv(index=False)
    encoded = base64.b64encode(csv_content.encode('utf-8')).decode('utf-8')
    data = {"message": f"Update {datetime.now()}", "content": encoded, "sha": sha}
    return requests.put(API_URL, headers=headers, data=json.dumps(data)).status_code in [200, 201]

# =========================
# 3. 各種エンジンの定義
# =========================
def parse_matsui(text):
    """松井証券のテキストを解析して数値を抽出"""
    try:
        num = lambda s: int(re.sub(r'[^\d]', '', s))
        res = {"現物": 0, "買残": 0, "売残": 0}
        p = re.search(r'([\d,]+)株\s*(買越し|売越し)', text)
        if p: res["現物"] = num(p.group(1)) * (1 if "買越し" in p.group(2) else -1)
        b = re.search(r'([\d,]+)株\s*(買残増|買残減)', text)
        if b: res["買残"] = num(b.group(1)) * (1 if "買残増" in b.group(2) else -1)
        s = re.search(r'([\d,]+)株\s*(売残増|売残減|売残)', text)
        if s: res["売残"] = num(s.group(1)) * (-1 if "売残減" in s.group(2) else 1)
        return res
    except: return None

# =========================
# 4. メイン UI
# =========================
st.title("🎯 Pre-Market Sniper V5.3")

# 起動時にGitHubからロード
if st.session_state.margin_df is None:
    st.session_state.margin_df = load_from_github()

# --- Step 1: スキャン ---
st.sidebar.subheader("🔍 Step 1: スキャン")
market = st.sidebar.radio("市場", ("プライム", "スタンダード", "グロース"))
min_val = st.sidebar.slider("最低売買代金(億)", 1, 50, 10)
if st.sidebar.button("スキャン開始", type="primary"):
    with st.spinner("一括データ取得中..."):
        master_url = "https://raw.githubusercontent.com/watarai0202-netizen/stocktest-app-1/main/data_j.csv"
        with urllib.request.urlopen(master_url) as resp:
            master = pd.read_csv(BytesIO(resp.read()))
        m_key = f"{market}（内国株式）"
        tickers = [f"{str(c).strip().replace('.0','')}.T" for c in master[master["市場・商品区分"] == m_key]["コード"]]
        
        found = []
        batch_size = 100
        for i in range(0, len(tickers), batch_size):
            batch = tickers[i:i+batch_size]
            df_p = yf.download(batch, period="1mo", interval="1d", group_by="ticker", progress=False)
            for t in batch:
                try:
                    data = df_p[t].dropna()
                    if len(data) < 15: continue
                    vol_y = data["Volume"].iloc[-1]
                    avg_vol = data["Volume"].iloc[-6:-1].mean()
                    rvol = vol_y / avg_vol
                    close_y = data["Close"].iloc[-1]
                    # RVOL & 10日高値ブレイク & 代金条件
                    if 1.15 <= rvol <= 1.6 and close_y >= data["High"].iloc[-11:-1].max() and (close_y * vol_y / 1e8) >= min_val:
                        found.append({"コード": int(t.replace(".T", "")), "rvol": rvol})
                        # 5MAをキャッシュに保存
                        st.session_state.price_cache[int(t.replace(".T", ""))] = data["Close"].tail(5).mean()
                except: continue
        
        # RVOL順に上位10銘柄を抽出
        sorted_f = sorted(found, key=lambda x: x["rvol"], reverse=True)[:10]
        st.session_state.candidates_df = pd.DataFrame(sorted_f)
        st.success("スキャン完了")

# --- Step 2: 需給入力 ---
st.subheader("📝 Step 2: 需給入力")
if not st.session_state.candidates_df.empty:
    # 候補と既存データの結合
    display_df = pd.merge(st.session_state.candidates_df[["コード"]], 
                          st.session_state.margin_df, on="コード", how="left").fillna(0)
    
    col1, col2 = st.columns([1, 2])
    with col1:
        t_code = st.selectbox("銘柄選択", display_df["コード"])
        p_text = st.text_area("松井テキストをペースト", height=100)
        if st.button("表に反映"):
            parsed = parse_matsui(p_text)
            if parsed:
                # メモリ上のデータを更新
                st.session_state.margin_df = st.session_state.margin_df[st.session_state.margin_df["コード"] != int(t_code)]
                new_row = pd.DataFrame([{
                    "コード": int(t_code), "信用買増": parsed["買残"], "信用売増": parsed["売残"], 
                    "現物差": parsed["現物"], "更新日": datetime.now().strftime("%Y-%m-%d")
                }])
                st.session_state.margin_df = pd.concat([st.session_state.margin_df, new_row])
                if "editor" in st.session_state: del st.session_state["editor"]
                st.rerun()
    
    with col2:
        edited_df = st.data_editor(display_df, use_container_width=True, key="editor")
    
    if st.button("💾 全入力をGitHubへ保存"):
        with st.spinner("同期中..."):
            if save_to_github(st.session_state.margin_df):
                st.success("GitHubの保存に成功しました！")

# --- Step 3: 指値算出 ---
if st.button("🚀 Step 3: 指値算出"):
    if edited_df.empty:
        st.warning("候補がありません")
    else:
        # 先物取得 (8:30時点の調整用)
        df_f = yf.download("NIY=F", period="1d", interval="5m", progress=False)
        f_rate = (df_f['Close'].iloc[-1] - df_f['Low'].min()) / (df_f['High'].max() - df_f['Low'].min())
        f_adj = 1.0 if f_rate >= 0.6 else 0.985 if f_rate <= 0.3 else 0.995
        
        res = []
        for _, row in edited_df.iterrows():
            code = int(row['コード'])
            ma5 = st.session_state.price_cache.get(code, 0)
            # 需給スコアリング
            score = (15 if row['信用売増'] > row['信用買増'] else 0) + (5 if row['現物差'] > 0 else 0) - (15 if row['信用買増'] > 50000 else 0)
            res.append({
                "コード": code, "5MA": f"{ma5:,.0f}", "需給スコア": score, 
                "理想指値": f"{ma5 * f_adj:,.0f}", "判定": "🎯狙撃" if score >= 15 else "慎重"
            })
        st.table(pd.DataFrame(res))
