import streamlit as st
import pandas as pd
import yfinance as yf
import urllib.request
from io import BytesIO
import re

# =========================
# 1. アプリ設定 & 認証
# =========================
st.set_page_config(page_title="Sniper V3.2 - Extreme Parser", layout="wide")
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
# 2. 強化版：需給解析エンジン
# =========================

def parse_matsui_paste(text):
    """
    全角スペース、改行、記号が混じったテキストから数値を抽出する
    """
    res = {"買残": 0, "売残": 0, "現物": 0, "code": None}
    
    # 1. 銘柄コード（4桁数字）を念のため探す
    code_match = re.search(r'(\d{4})', text)
    if code_match: res["code"] = code_match.group(1)

    # 2. 「数値 + 株 + キーワード」のパターンをすべて抽出
    # 数値の後の「株」から、次の空白や記号までの文字列をセットで探します
    matches = re.finditer(r'([\d,]+)株\s*([^\s\n＞]+)', text)
    
    found_any = False
    for m in matches:
        try:
            val = int(m.group(1).replace(',', ''))
            key = m.group(2)
            
            # 現物判定
            if "買越し" in key: 
                res["現物"] = val
                found_any = True
            elif "売越し" in key: 
                res["現物"] = -val
                found_any = True
            
            # 信用買残判定
            elif "買残" in key:
                if "増" in key: res["買残"] = val
                elif "減" in key: res["買残"] = -val
                found_any = True
                
            # 信用売残判定
            elif "売残" in key:
                if "減" in key: res["売残"] = -val
                else: res["売残"] = val # 「売残増」または単なる「売残」に対応
                found_any = True
        except:
            continue

    return res if found_any else None

# =========================
# 3. スキャン & 先物ロジック
# =========================

@st.cache_data(ttl=3600)
def load_master():
    url = "https://raw.githubusercontent.com/watarai0202-netizen/stocktest-app-1/main/data_j.csv"
    with urllib.request.urlopen(url) as resp:
        return pd.read_csv(BytesIO(resp.read()))

def get_futures():
    try:
        df = yf.download("NIY=F", period="1d", interval="5m", progress=False)
        if df.empty: return "不明", 1.0
        h, l, c = df['High'].max(), df['Low'].min(), df['Close'].iloc[-1]
        rate = (c - l) / (h - l) if (h - l) > 0 else 0
        if rate >= 0.6: return "🔥V字 (強気)", 1.0
        if rate <= 0.3: return "⚠️L字 (慎重)", 0.985
        return "⚖️通常", 0.995
    except: return "不明", 1.0

# =========================
# 4. メイン UI
# =========================
st.title("🎯 Pre-Market Sniper V3.2")

# --- Step 1 ---
st.sidebar.subheader("🔍 Step 1")
market = st.sidebar.radio("市場", ("プライム", "スタンダード", "グロース"))
if st.sidebar.button("上位20銘柄を抽出"):
    master = load_master()
    m_key = f"{market}（内国株式）"
    ts = [f"{str(c).strip().replace('.0','')}.T" for c in master[master["市場・商品区分"] == m_key]["コード"]]
    found = []
    status = st.empty()
    for i in range(0, len(ts), 50):
        status.text(f"スキャン中... {i}/{len(ts)}")
        df_p = yf.download(ts[i:i+50], period="1mo", interval="1d", group_by="ticker", progress=False)
        for t in ts[i:i+50]:
            try:
                d = df_p[t].dropna()
                rvol = d["Volume"].iloc[-1] / d["Volume"].iloc[-6:-1].mean()
                if 1.15 <= rvol <= 1.6 and d["Close"].iloc[-1] >= d["High"].iloc[-11:-1].max():
                    found.append({"コード": t.replace(".T", ""), "val": d["Close"].iloc[-1] * d["Volume"].iloc[-1]})
            except: continue
    status.empty()
    top20 = sorted(found, key=lambda x: x["val"], reverse=True)[:20]
    st.session_state.candidates_df = pd.DataFrame([{"コード": c["コード"], "信用買増": 0, "信用売増": 0, "現物差": 0} for c in top20])
    st.success("抽出完了。")

# --- Step 2: コピペ入力エリア ---
st.subheader("📝 Step 2: 需給コピペ入力")
if not st.session_state.candidates_df.empty:
    col_input, col_table = st.columns([1, 2])
    
    with col_input:
        target_code = st.selectbox("対象銘柄を選択", st.session_state.candidates_df["コード"])
        paste_area = st.text_area("松井証券のテキストを貼り付け", height=150, placeholder="例：1,043,600株買越し\n613,500株 買残減...")
        
        if st.button("反映する"):
            parsed = parse_matsui_paste(paste_area)
            if parsed:
                # 選択中のコードに対して数値を上書き
                idx = st.session_state.candidates_df[st.session_state.candidates_df["コード"] == target_code].index
                st.session_state.candidates_df.loc[idx, ["信用買増", "信用売増", "現物差"]] = [parsed["買残"], parsed["売残"], parsed["現物"]]
                st.toast(f"{target_code} のデータを解析・更新しました！")
                
                # テキストに別のコードが含まれていた場合のアラート
                if parsed["code"] and parsed["code"] != target_code:
                    st.warning(f"注意：貼り付けたテキストはコード {parsed['code']} のものかもしれません。")
            else:
                st.error("解析できませんでした。コピーした範囲を確認してください。")

    with col_table:
        edited_df = st.data_editor(st.session_state.candidates_df, use_container_width=True, key="editor")

# --- Step 3 ---
if st.button("🚀 Step 3: 指値算出"):
    f_stat, f_adj = get_futures()
    st.info(f"先物判定: {f_stat}")
    t_ticks = [f"{c}.T" for c in edited_df["コード"]]
    df_f = yf.download(t_ticks, period="5d", interval="1d", group_by="ticker", progress=False)
    final = []
    for _, row in edited_df.iterrows():
        t = f"{row['コード']}.T"
        if t not in df_f.columns.levels[0]: continue
        ma5 = df_f[t]["Close"].dropna().tail(5).mean()
        # 需給スコア: 売残増(+)、現物買越(+)、買残増(-)
        score = (15 if row['信用売増'] > row['信用買増'] else 0) + (5 if row['現物差'] > 0 else 0) - (15 if row['信用買増'] > 50000 else 0)
        final.append({"コード": row['コード'], "5MA": f"{ma5:,.0f}", "需給スコア": score, "指値": f"{ma5 * f_adj:,.0f}", "判定": "🎯狙撃" if score >= 15 else "慎重"})
    st.table(pd.DataFrame(final))
