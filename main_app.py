import streamlit as st
import pandas as pd
import yfinance as yf
import numpy as np
from datetime import datetime

# =========================
# 1. 需給・先物判定ロジック
# =========================

def analyze_futures_trend():
    """8:30時点の先物トレンドを判定（V字/L字）"""
    try:
        # 日経225先物(CME)を取得
        df_f = yf.download("NIY=F", period="1d", interval="5m", progress=False)
        if df_f.empty: return "データ無", 1.0, 0
        
        high = df_f['High'].max()
        low = df_f['Low'].min()
        curr = df_f['Close'].iloc[-1]
        
        drop = high - low
        recovery = curr - low
        rate = recovery / drop if drop > 0 else 0
        
        # 戻し率による判定
        if rate >= 0.6: return "🔥V字回復", 1.0, rate
        if rate <= 0.3: return "⚠️L字停滞", 0.98, rate # 指値を2%下げる調整
        return "⚖️通常", 0.99, rate
    except:
        return "取得エラー", 1.0, 0

def calc_supply_score(row):
    """松井証券の需給データをスコア化"""
    score = 0
    # 信用売増 > 信用買増 ならポジティブ
    if row['信用売増'] > row['信用買増']: score += 15
    # 買残が多すぎると「寄り底偽装の下げ」リスク
    if row['信用買増'] > 50000: score -= 15 
    return score

# =========================
# 2. 既存アプリへの統合（メインスキャン部分）
# =========================

# --- サイドバー：需給データ入力（手打ち用） ---
st.sidebar.subheader("📝 松井証券 需給入力")
input_df = st.sidebar.data_editor(
    pd.DataFrame([{"コード": "6590", "信用買増": 0, "信用売増": 0, "現物差": 0}]),
    num_rows="dynamic", key="margin_editor"
)

# --- メイン画面：スキャン実行 ---
if st.button("📡 スナイパー・スキャン開始", type="primary"):
    f_status, f_adj, f_rate = analyze_futures_trend()
    st.write(f"【先物状況】{f_status} (戻し率: {f_rate:.1%})")

    # (中略: Ticker取得、価格フェッチ処理)

    results = []
    for t in batch:
        data = df[t].dropna()
        if len(data) < 10: continue
        
        # --- 戦略指標の計算 ---
        curr = float(data["Close"].iloc[-1])
        vol = float(data["Volume"].iloc[-1])
        
        # 1. RVOL (1.2-1.3倍)
        avg_vol5 = data["Volume"].tail(5).mean()
        rvol = vol / avg_vol5
        
        # 2. 5MA算出
        ma5 = data["Close"].tail(5).mean()
        dist_ma5 = (curr - ma5) / ma5 * 100
        
        # 3. 10日高値ブレイク
        recent_high = data["High"].iloc[-11:-1].max()
        is_breakout = curr > recent_high
        
        # 4. 理想指値の算出
        # 先物のトレンドに合わせて5MAの位置を微調整
        target_price = ma5 * f_adj 
        
        # 5. 需給スコアの合算
        code_str = t.replace(".T", "")
        m_row = input_df[input_df["コード"] == code_str]
        s_score = calc_supply_score(m_row.iloc[0]) if not m_row.empty else 0
        
        # --- フィルタリング条件 ---
        if 1.1 <= rvol <= 1.5 and is_breakout:
            results.append({
                "コード": code_str,
                "銘柄名": info_db.get(t, ["-"])[0],
                "RVOL": f"{rvol:.2f}x",
                "5MA乖離": f"{dist_ma5:+.2f}%",
                "需給スコア": s_score,
                "理想指値": f"{target_price:,.0f}",
                "判定": "🎯狙撃" if s_score >= 0 else "慎重"
            })

    # 結果表示
    if results:
        st.table(pd.DataFrame(results))
    else:
        st.warning("条件に合致する銘柄が見つかりませんでした。")
