import io
import numpy as np
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Kreditinių SUM → SUM SU PVM", page_icon="✅", layout="wide")

uploaded = st.file_uploader("Įkelk Excel (.xlsx) be antraščių", type=["xlsx"])

def detect_currency_column(df, currency):
    eur_idx, max_cnt = None, -1
    for c in df.columns:
        col = df[c].astype(str).str.strip()
        cnt = (col == currency).sum()
        if cnt > max_cnt:
            eur_idx, max_cnt = c, cnt
    if eur_idx is None or max_cnt <= 0:
        raise ValueError("Nerasta valiuta.")
    return eur_idx

def parse_amount(series):
    s = (series.astype(str)
         .str.replace("\u00A0"," ", regex=False)
         .str.replace(" ", "", regex=False)
         .str.replace(",", ".", regex=False))
    return pd.to_numeric(s, errors="coerce")

if uploaded:
    df = pd.read_excel(uploaded, header=None, engine="openpyxl")
    eur_col = detect_currency_column(df, "EUR")
    amount_col = eur_col - 1

    amounts = parse_amount(df[amount_col])
    df["SUM SU PVM"] = amounts

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df.to_excel(w, index=False, header=False)
    buf.seek(0)

    st.download_button("Parsisiųsti", buf,
                       "kreditines_su_sum.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
