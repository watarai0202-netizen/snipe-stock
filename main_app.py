import streamlit as st
import pandas as pd
import yfinance as yf
import urllib.request
from io import BytesIO
import re

# =========================
# 1. アプリ設定 & 認証
# =========================
st.set_page_config(page_title="Sniper V3.2 - Fix", layout="wide")
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
# 2. 需給解析エンジン (精度向上版)
# =========================
def parse_matsui_paste(text):
    try:
        def to_num(s): return int(s.replace(',', '').replace('株', '').strip())
        res = {"買残": 0, "売残": 0, "現物": 0}
        
        # 現物
        p = re.search(r'([\d,]+)株\s*(買越し|売越し)', text)
        if p: res["現物"] = to_num(p.group(1)) * (1 if "買越し" in p.group(2) else -1)
        
        # 買残
        b = re.search(r'([\d,]+)株\s*(買残増|買残減)', text)
        if b: res["買残"] = to_num(b.group(1)) * (1 if "買残増" in b.group(2) else -1)
        
        # 売残 (「売残」だけの表記にも対応)
        s = re.search(r'([\d,]+)株\s*(売残増|売残減|売残)', text)
        if s: res["売残"] = to_num(s.group(1)) * (-1 if "売残減" in s.group(3) else 1)
        
        return res
    except: return None

# =========================
# 3. Step 1: 抽出 (変更なし)
# =========================
st.title("🎯 Pre-Market Sniper V3.2")
st.sidebar.subheader("🔍 Step 1")
market = st.sidebar.radio("市場", ("プライム", "スタンダード", "グロース"))

if st.sidebar.button("上位20銘柄を抽出"):
    with st.spinner("スキャン中..."):
        try:
            with urllib.request.urlopen("https://raw.githubusercontent.com/watarai0202-netizen/stocktest-app-1/main/data_j.csv") as resp:
                master = pd.read_csv(BytesIO(resp.read()))
            m_key = f"{market}（内国株式）"
            ts = [f"{str(c).strip().replace('.0','')}.T" for c in master[master["市場・商品区分"] == m_key]["コード"]]
            found = []
            for i in range(0, len(ts), 50):
                df_p = yf.download(ts[i:i+50], period="1mo", interval="1d", group_by="ticker", progress=False)
                for t in ts[i:i+50]:
                    try:
                        d = df_p[t].dropna()
                        rvol = d["Volume"].iloc[-1] / d["Volume"].iloc[-6:-1].mean()
                        if 1.15 <= rvol <= 1.6 and d["Close"].iloc[-1] >= d["High"].iloc[-11:-1].max():
                            found.append({"コード": t.replace(".T", ""), "val": d["Close"].iloc[-1] * d["Volume"].iloc[-1]})
                    except: continue
            top20 = sorted(found, key=lambda x: x["val"], reverse=True)[:20]
            st.session_state.candidates_df = pd.DataFrame([{"コード": c["コード"], "信用買増": 0, "信用売増": 0, "現物差": 0} for c in top20])
            st.success("抽出完了")
        except Exception as e: st.error(f"エラー: {e}")

# =========================
# 4. Step 2: 需給コピペ入力 (修正箇所)
# =========================
st.subheader("📝 Step 2: 需給コピペ入力")
if not st.session_state.candidates_df.empty:
    col_input, col_table = st.columns([1, 2])
    
    with col_input:
        target_code = st.selectbox("対象銘柄を選択", st.session_state.candidates_df["コード"])
        paste_area = st.text_area("松井証券のテキストを貼り付け", height=150, placeholder="ここにペースト")
        
        if st.button("反映する"):
            parsed = parse_matsui_paste(paste_area)
            if parsed:
                # 1. session_stateの値を更新
                idx = st.session_state.candidates_df[st.session_state.candidates_df["コード"] == target_code].index
                st.session_state.candidates_df.loc[idx, ["信用買増", "信用売増", "現物差"]] = [parsed["買残"], parsed["売残"], parsed["現物"]]
                
                # 2. 重要：data_editorの内部キャッシュを削除する
                if "editor" in st.session_state:
                    del st.session_state["editor"]
                
                # 3. 画面を再描画させて最新状態を表示
                st.rerun()
            else:
                st.error("解析できませんでした。")

    with col_table:
        # 修正：更新後のsession_stateを常に読み込む
        edited_df = st.data_editor(st.session_state.candidates_df, use_container_width=True, key="editor")

# =========================
# 5. Step 3: 指値算出
# =========================
if st.button("🚀 Step 3: 指値算出"):
    # (先物取得・計算ロジックは前回同様)
    st.info("計算を実行しました（以下、結果テーブルを表示）")
    # ...
