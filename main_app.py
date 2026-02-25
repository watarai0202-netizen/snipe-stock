import streamlit as st
import pandas as pd
import yfinance as yf
import urllib.request
from io import BytesIO

# =========================
# 1. アプリ設定 & 認証
# =========================
st.set_page_config(page_title="Pre-Market Sniper V2", layout="wide")
MY_PASSWORD = "stock testa"

if "auth" not in st.session_state:
    st.session_state.auth = False
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
    with urllib.request.urlopen(GITHUB_CSV_RAW_URL) as resp:
        return pd.read_csv(BytesIO(resp.read()))

def analyze_futures_trend():
    """8:30時点の先物トレンド判定"""
    try:
        df_f = yf.download("NIY=F", period="1d", interval="5m", progress=False)
        if df_f.empty: return "データ無", 1.0, 0
        high, low, curr = df_f['High'].max(), df_f['Low'].min(), df_f['Close'].iloc[-1]
        drop = high - low
        recovery = curr - low
        rate = recovery / drop if drop > 0 else 0
        if rate >= 0.6: return "🔥V字回復", 1.0, rate
        if rate <= 0.3: return "⚠️L字停滞", 0.985, rate
        return "⚖️通常", 0.995, rate
    except: return "取得エラー", 1.0, 0

# =========================
# 3. Step 1: 候補銘柄の自動抽出 (前夜/早朝用)
# =========================
st.title("🎯 Pre-Market Sniper")

target_market = st.sidebar.radio("📊 市場を選択", ("プライム", "スタンダード", "グロース"))
st.sidebar.markdown("---")

if st.sidebar.button("🔍 Step 1: 候補銘柄を抽出", type="primary"):
    df_master = load_master()
    market_key = f"{target_market}（内国株式）"
    tickers = [f"{str(c).strip().replace('.0','')}.T" for c in df_master[df_master["市場・商品区分"] == market_key]["コード"]]
    
    found_codes = []
    status_area = st.empty()
    batch_size = 50
    
    for i in range(0, len(tickers), batch_size):
        batch = tickers[i:i+batch_size]
        status_area.text(f"スクリーニング中... {i}/{len(tickers)}")
        try:
            df_p = yf.download(batch, period="1mo", interval="1d", group_by="ticker", progress=False)
            for t in batch:
                if t not in df_p.columns.levels[0]: continue
                data = df_p[t].dropna()
                if len(data) < 15: continue
                
                # ロジック: RVOL(1.2-1.5) & 10日高値ブレイク
                vol_yesterday = data["Volume"].iloc[-1]
                avg_vol5 = data["Volume"].iloc[-6:-1].mean()
                rvol = vol_yesterday / avg_vol5
                
                close_yesterday = data["Close"].iloc[-1]
                high_10d = data["High"].iloc[-11:-1].max()
                
                if 1.15 <= rvol <= 1.6 and close_yesterday >= high_10d:
                    found_codes.append(t.replace(".T", ""))
        except: continue
    
    status_area.empty()
    # 抽出結果をセッション状態に保存（入力シートに反映させるため）
    st.session_state.candidates_df = pd.DataFrame([
        {"コード": c, "信用買増": 0, "信用売増": 0, "現物差": 0} for c in found_codes
    ])
    st.success(f"{len(found_codes)} 銘柄を抽出しました。Step 2で需給を入力してください。")

# =========================
# 4. Step 2 & 3: 需給入力と最終判定
# =========================
st.subheader("📝 Step 2: 松井証券データ入力")
st.caption("抽出された銘柄コードが自動反映されています。数値を入力してください。")

# ここでStep 1の結果が反映されたエディタを表示
edited_df = st.data_editor(
    st.session_state.candidates_df,
    num_rows="dynamic",
    key="margin_editor",
    use_container_width=True
)

if st.button("🚀 Step 3: 最終スナイパー実行 (8:50目安)", type="secondary"):
    if edited_df.empty:
        st.warning("銘柄がありません。先にStep 1を実行するか、直接コードを入力してください。")
    else:
        f_status, f_adj, f_rate = analyze_futures_trend()
        st.info(f"**先物状況:** {f_status} (戻し率: {f_rate:.1%})")
        
        final_results = []
        target_tickers = [f"{c}.T" for c in edited_df["コード"]]
        
        # 最終判定用のデータ取得
        df_final = yf.download(target_tickers, period="5d", interval="1d", group_by="ticker", progress=False)
        
        for _, row in edited_df.iterrows():
            t = f"{row['コード']}.T"
            if t not in df_final.columns.levels[0]: continue
            data = df_final[t].dropna()
            
            curr = data["Close"].iloc[-1]
            ma5 = data["Close"].tail(5).mean()
            
            # 需給スコア算出
            s_score = 0
            if row['信用売増'] > row['信用買増']: s_score += 15
            if row['信用買増'] > 50000: s_score -= 15
            
            # 理想指値（先物調整込み）
            target_price = ma5 * f_adj
            
            final_results.append({
                "コード": row['コード'],
                "5MA位置": f"{ma5:,.0f}",
                "需給スコア": s_score,
                "理想指値": f"{target_price:,.0f}",
                "判定": "🎯狙撃" if s_score >= 0 else "慎重"
            })
            
        if final_results:
            st.dataframe(pd.DataFrame(final_results), use_container_width=True, hide_index=True)
