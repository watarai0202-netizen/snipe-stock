import streamlit as st
import pandas as pd
import yfinance as yf
import urllib.request
from io import BytesIO
import re

# =========================
# 1. アプリ設定 & 認証
# =========================
st.set_page_config(page_title="Sniper V3.3 - Stable", layout="wide")
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
# 2. 需給解析エンジン (正規表現 修正版)
# =========================
def parse_matsui_paste(text):
    """松井証券のコピペ形式を数値化。符号判定を自動化"""
    try:
        # 数字以外（カンマや単位）を除去して数値化する補助関数
        def to_num(s): return int(re.sub(r'[^\d]', '', s))
        
        res = {"買残": 0, "売残": 0, "現物": 0}
        
        # 1. 現物 (買越しなら正、売越しなら負)
        p = re.search(r'([\d,]+)株\s*(買越し|売越し)', text)
        if p:
            res["現物"] = to_num(p.group(1)) * (1 if "買越し" in p.group(2) else -1)
            
        # 2. 信用買残 (買残増なら正、買残減なら負)
        b = re.search(r'([\d,]+)株\s*(買残増|買残減)', text)
        if b:
            res["買残"] = to_num(b.group(1)) * (1 if "買残増" in b.group(2) else -1)
            
        # 3. 信用売残 (売残増・売残なら正、売残減なら負)
        s = re.search(r'([\d,]+)株\s*(売残増|売残減|売残)', text)
        if s:
            # group indexを2に修正し、エラーを解消
            res["売残"] = to_num(s.group(1)) * (-1 if "売残減" in s.group(2) else 1)
        
        # 解析成功判定
        if p or b or s:
            return res
        return None
    except:
        return None

# =========================
# 3. Step 1: 候補銘柄の自動抽出 (上位20)
# =========================
st.title("🎯 Pre-Market Sniper V3.3")

st.sidebar.subheader("🔍 Step 1: スキャン")
market = st.sidebar.radio("市場を選択", ("プライム", "スタンダード", "グロース"))
top_n = st.sidebar.slider("抽出上限（売買代金順）", 5, 50, 20)

if st.sidebar.button("スクリーニング開始", type="primary"):
    with st.spinner("スキャン中..."):
        try:
            with urllib.request.urlopen("https://raw.githubusercontent.com/watarai0202-netizen/stocktest-app-1/main/data_j.csv") as resp:
                master = pd.read_csv(BytesIO(resp.read()))
            m_key = f"{market}（内国株式）"
            tickers = [f"{str(c).strip().replace('.0','')}.T" for c in master[master["市場・商品区分"] == m_key]["コード"]]
            
            candidate_list = []
            status_area = st.empty()
            batch_size = 50
            for i in range(0, len(tickers), batch_size):
                batch = tickers[i:i+batch_size]
                status_area.text(f"処理中... {i}/{len(tickers)}")
                df_p = yf.download(batch, period="1mo", interval="1d", group_by="ticker", progress=False)
                for t in batch:
                    try:
                        data = df_p[t].dropna()
                        if len(data) < 15: continue
                        # RVOL & ブレイクアウト判定
                        vol_y = data["Volume"].iloc[-1]
                        avg_vol = data["Volume"].iloc[-6:-1].mean()
                        rvol = vol_y / avg_vol
                        close_y = data["Close"].iloc[-1]
                        hi_10d = data["High"].iloc[-11:-1].max()
                        
                        if 1.15 <= rvol <= 1.6 and close_y >= hi_10d:
                            candidate_list.append({"コード": t.replace(".T", ""), "val": close_y * vol_y})
                    except: continue
            
            status_area.empty()
            # 売買代金順にソートして上位20件をセッションへ保存
            sorted_f = sorted(candidate_list, key=lambda x: x["val"], reverse=True)[:top_n]
            st.session_state.candidates_df = pd.DataFrame([{"コード": c["コード"], "信用買増": 0, "信用売増": 0, "現物差": 0} for c in sorted_f])
            st.success(f"{len(sorted_f)} 銘柄を抽出。Step 2へ。")
        except Exception as e: st.error(f"エラー: {e}")

# =========================
# 4. Step 2: 需給データの入力
# =========================
st.subheader("📝 Step 2: 需給コピペ入力")
if not st.session_state.candidates_df.empty:
    col_input, col_table = st.columns([1, 2])
    
    with col_input:
        target_code = st.selectbox("対象コードを選択", st.session_state.candidates_df["コード"])
        paste_area = st.text_area("松井のテキストをペースト", height=150, placeholder="例: 1,043,600株買越し...")
        
        if st.button("反映する"):
            parsed = parse_matsui_paste(paste_area)
            if parsed:
                # session_stateを更新
                idx = st.session_state.candidates_df[st.session_state.candidates_df["コード"] == target_code].index
                st.session_state.candidates_df.loc[idx, ["信用買増", "信用売増", "現物差"]] = [parsed["買残"], parsed["売残"], parsed["現物"]]
                # キャッシュ破棄と再描画
                if "editor" in st.session_state: del st.session_state["editor"]
                st.rerun()
            else:
                st.error("解析できません。形式を確認してください。")

    with col_table:
        edited_df = st.data_editor(st.session_state.candidates_df, use_container_width=True, key="editor")

# =========================
# 5. Step 3: 狙撃ポイント算出
# =========================
if st.button("🚀 Step 3: 最終計算 (指値算出)", type="secondary"):
    if edited_df.empty:
        st.warning("候補がありません。")
    else:
        # 先物判定 (8:30時点)
        try:
            df_f = yf.download("NIY=F", period="1d", interval="5m", progress=False)
            h, l, c = df_f['High'].max(), df_f['Low'].min(), df_f['Close'].iloc[-1]
            f_rate = (c - l) / (h - l) if (h - l) > 0 else 0
            f_adj = 1.0 if f_rate >= 0.6 else 0.985 if f_rate <= 0.3 else 0.995
            st.info(f"**先物状況:** {'🔥V字' if f_rate >= 0.6 else '⚠️L字' if f_rate <= 0.3 else '⚖️通常'} (戻し率: {f_rate:.1%})")
        except: f_adj = 1.0; st.warning("先物取得不可")

        # 最終判定
        t_ticks = [f"{c}.T" for c in edited_df["コード"]]
        df_f = yf.download(t_ticks, period="5d", interval="1d", group_by="ticker", progress=False)
        final = []
        for _, row in edited_df.iterrows():
            t = f"{row['コード']}.T"
            if t not in df_f.columns.levels[0]: continue
            ma5 = df_f[t]["Close"].dropna().tail(5).mean()
            # 需給スコアリング
            score = (15 if row['信用売増'] > row['信用買増'] else 0) + (5 if row['現物差'] > 0 else 0) - (15 if row['信用買増'] > 50000 else 0)
            final.append({
                "コード": row['コード'], "5MA": f"{ma5:,.0f}", "需給スコア": score, 
                "理想指値": f"{ma5 * f_adj:,.0f}", "判定": "🎯狙撃" if score >= 15 else "慎重"
            })
        st.table(pd.DataFrame(final))
