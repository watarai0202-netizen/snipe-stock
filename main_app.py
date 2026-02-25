import streamlit as st
import pandas as pd
import yfinance as yf
import os
import urllib.request
from io import BytesIO

# =========================
# 1. アプリ設定 & 認証
# =========================
st.set_page_config(page_title="Pre-Market Sniper", layout="wide")
MY_PASSWORD = "stock testa"

if "auth" not in st.session_state:
    st.session_state.auth = False

if not st.session_state.auth:
    st.title("🔒 認証")
    pwd = st.text_input("パスワード", type="password")
    if pwd == MY_PASSWORD:
        st.session_state.auth = True
        st.rerun()
    st.stop()

# =========================
# 2. 定数 & GitHub CSV
# =========================
GITHUB_CSV_RAW_URL = "https://raw.githubusercontent.com/watarai0202-netizen/stocktest-app-1/main/data_j.csv"

# =========================
# 3. 新規：スナイパー・ロジック関数
# =========================

def analyze_futures_trend():
    """8:30時点の先物トレンド判定"""
    try:
        # 日経225先物(CME)
        df_f = yf.download("NIY=F", period="1d", interval="5m", progress=False)
        if df_f.empty: return "データ無", 1.0, 0
        
        high = df_f['High'].max()
        low = df_f['Low'].min()
        curr = df_f['Close'].iloc[-1]
        
        drop = high - low
        recovery = curr - low
        rate = recovery / drop if drop > 0 else 0
        
        # 戻し率判定
        if rate >= 0.6: return "🔥V字回復 (強気)", 1.0, rate
        if rate <= 0.3: return "⚠️L字停滞 (指値下げ推奨)", 0.985, rate
        return "⚖️通常", 0.995, rate
    except:
        return "取得エラー", 1.0, 0

def calc_supply_score(row):
    """松井証券の需給データをスコア化"""
    score = 0
    if row['信用売増'] > row['信用買増']: score += 15
    if row['信用買増'] > 50000: score -= 15 # しこり警戒
    return score

# =========================
# 4. サイドバー設定
# =========================
st.sidebar.title("⚙️ Sniper Settings")

# 需給データ手入力セクション
st.sidebar.subheader("📝 松井証券 需給入力")
input_df = st.sidebar.data_editor(
    pd.DataFrame([{"コード": "6590", "信用買増": 0, "信用売増": 0, "現物差": 0}]),
    num_rows="dynamic", key="margin_editor"
)

target_market = st.sidebar.radio("📊 市場を選択", ("プライム", "スタンダード", "グロース"))

# =========================
# 5. スキャン実行
# =========================

# マスター読み込み
@st.cache_data(ttl=3600)
def load_master():
    with urllib.request.urlopen(GITHUB_CSV
