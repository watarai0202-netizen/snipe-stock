import streamlit as st
import pandas as pd
import yfinance as yf
import urllib.request
from io import BytesIO

# =========================
# 1. アプリ基本設定 & 認証
# =========================
st.set_page_config(page_title="Pre-Market Sniper V2.1", layout="wide")
MY_PASSWORD = "stock testa"

if "auth" not in st.session_state:
    st.session_state.auth = False
# Step 1の結果を保持するためのセッション状態
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
# 2. 定数 & ユーティリティ
# =========================
GITHUB_CSV_RAW_URL = "https://raw.githubusercontent.com/watarai0202-netizen/stocktest-app-1/main/data_j.csv"

@st.cache_data(ttl=3600)
def load_master():
    """GitHubから銘柄マスタを読み込む"""
    with urllib.request.urlopen(GITHUB_CSV_RAW_URL) as resp:
        return pd.read_csv(BytesIO(resp.read()))

def analyze_futures_trend():
    """8:30時点の先物トレンド（V字/L字）を判定"""
    try:
        df_f = yf.download("NIY=F", period="1d", interval="5m", progress=False)
        if df_f.empty: return "データ無", 1.0, 0
        high, low, curr = df_f['High'].max(), df_f['Low'].min(), df_f['Close'].iloc[-1]
        drop = high - low
        recovery = curr - low
        rate = recovery / drop if drop > 0 else 0
        # 戻し率による判定基準
        if rate >= 0.6: return "🔥V字回復 (強気)", 1.0, rate
        if rate <= 0.3: return "⚠️L字停滞 (指値下げ推奨)", 0.985, rate
        return "⚖️通常", 0.995, rate
    except: return "取得エラー", 1.0, 0

# =========================
# 3. Step 1: 候補銘柄の自動抽出 (売買代金上位20)
# =========================
st.title("🎯 Pre-Market Sniper")

st.sidebar.title("⚙️ 設定")
target_market = st.sidebar.radio("📊 市場を選択", ("プライム", "スタンダード", "グロース"))
top_n = st.sidebar.slider("📈 抽出上限（売買代金順）", 5, 50, 20)
st.sidebar.markdown("---")

if st.sidebar.button("🔍 Step 1: スクリーニング開始", type="primary"):
    df_master = load_master()
    market_key = f"{target_market}（内国株式）"
    tickers = [f"{str(c).strip().replace('.0','')}.T" for c in df_master[df_master["市場・商品区分"] == market_key]["コード"]]
    
    candidate_list = []
    status_area = st.empty()
    batch_size = 50
    
    for i in range(0, len(tickers), batch_size):
        batch = tickers[i:i+batch_size]
        status_area.text(f"スキャン中... {i}/{len(tickers)}")
        try:
            # 1ヶ月分の日足を一括取得
            df_p = yf.download(batch, period="1mo", interval="1d", group_by="ticker", progress=False)
            for t in batch:
                if t not in df_p.columns.levels[0]: continue
                data = df_p[t].dropna()
                if len(data) < 15: continue
                
                # 条件判定: RVOL (1.15-1.6x) & 10日高値ブレイク
                vol_yest = data["Volume"].iloc[-1]
                close_yest = data["Close"].iloc[-1]
                avg_vol5 = data["Volume"].iloc[-6:-1].mean()
                rvol = vol_yest / avg_vol5
                
                high_10d = data["High"].iloc[-11:-1].max()
                
                if 1.15 <= rvol <= 1.6 and close_yest >= high_10d:
                    # 売買代金を算出
                    t_value = close_yest * vol_yest
                    candidate_list.append({"コード": t.replace(".T", ""), "売買代金": t_value})
        except: continue
    
    status_area.empty()
    # 売買代金順にソートして上位N件に絞り込み
    sorted_list = sorted(candidate_list, key=lambda x: x["売買代金"], reverse=True)[:top_n]
    
    # セッション状態を更新し、入力シートへ反映
    st.session_state.candidates_df = pd.DataFrame([
        {"コード": c["コード"], "信用買増": 0, "信用売増": 0, "現物差": 0} for c in sorted_list
    ])
    st.success(f"売買代金上位 {len(sorted_list)} 銘柄を抽出しました。Step 2へ進んでください。")

# =========================
# 4. Step 2: 需給データ入力
# =========================
st.subheader("📝 Step 2: 松井証券 需給データ入力")
st.caption("Step 1の結果が自動反映されます。数値を入力してください。")

edited_df = st.data_editor(
    st.session_state.candidates_df,
    num_rows="dynamic",
    key="margin_editor",
    use_container_width=True
)

# =========================
# 5. Step 3: 最終スナイパー実行 (8:50目安)
# =========================
if st.button("🚀 Step 3: 理想指値を算出", type="secondary"):
    if edited_df.empty:
        st.warning("候補銘柄がありません。先にStep 1を実行してください。")
    else:
        # 先物トレンドを取得
        f_status, f_adj, f_rate = analyze_futures_trend()
        st.info(f"**【先物判定】** {f_status} (戻し率: {f_rate:.1%})")
        
        final_results = []
        target_tickers = [f"{c}.T" for c in edited_df["コード"]]
        
        # 5MA算出用の最新日足取得
        df_final = yf.download(target_tickers, period="5d", interval="1d", group_by="ticker", progress=False)
        
        for _, row in edited_df.iterrows():
            t = f"{row['コード']}.T"
            if t not in df_final.columns.levels[0]: continue
            data = df_final[t].dropna()
            
            # 5MAの計算
            ma5 = data["Close"].tail(5).mean()
            
            # 需給スコアの計算
            s_score = 0
            if row['信用売増'] > row['信用買増']: s_score += 15
            if row['信用買増'] > 50000: s_score -= 15
            
            # 理想指値の計算（先物調整を反映）
            target_price = ma5 * f_adj
            
            final_results.append({
                "コード": row['コード'],
                "5MA位置": f"{ma5:,.0f}",
                "需給スコア": s_score,
                "理想指値": f"{target_price:,.0f}",
                "判定": "🎯狙撃" if s_score >= 0 else "慎重"
            })
            
        if final_results:
            st.table(pd.DataFrame(final_results))
