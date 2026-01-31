import streamlit as st
import pandas as pd

st.header("📥 Įkėlimas")

def read_by_letters(file_or_buf,
                    names=("Data","Saskaitos_NR","Klientas","SutartiesID","Suma")) -> pd.DataFrame:
    """
    Skaito Excel BE antraščių ir paima konkrečius stulpelius:
    A=Data, B=Sąskaitos_NR, D=Klientas, F=SutartiesID, G=Suma.
    (SVARBU: usecols – VIENAS string, o ne sąrašas -> nebus ValueError)
    """
    df = pd.read_excel(
        file_or_buf,
        header=None,
        engine="openpyxl",
        usecols="A,B,D,F,G"
    )
    df.columns = list(names)

    # Tipai ir sanitarija
    df["Data"] = pd.to_datetime(df["Data"], errors="coerce")
    df["Suma"] = pd.to_numeric(df["Suma"], errors="coerce")
    for c in ("Klientas","SutartiesID","Saskaitos_NR"):
        df[c] = df[c].astype(str).str.strip()

    # Pas tave be PVM -> lygu Suma
    df["Suma_su_PVM"] = df["Suma"].fillna(0.0)
    return df

col1, col2 = st.columns(2)

with col1:
    inv_file = st.file_uploader("Sąskaitos.xlsx", type=["xlsx"], key="upl_inv")
    if inv_file:
        st.session_state["inv_norm"] = read_by_letters(inv_file)
        st.success("✅ Sąskaitos nuskaitytos ir įrašytos į session_state['inv_norm'].")

with col2:
    crn_file = st.file_uploader("Kreditinės.xlsx", type=["xlsx"], key="upl_crn")
    if crn_file:
        st.session_state["crn_norm"] = read_by_letters(crn_file)
        st.success("✅ Kreditinės nuskaitytos ir įrašytos į session_state['crn_norm'].")

# Greita peržiūra
if "inv_norm" in st.session_state:
    st.subheader("Peržiūra – Sąskaitos")
    st.dataframe(st.session_state["inv_norm"].head(20), use_container_width=True)

if "crn_norm" in st.session_state:
    st.subheader("Peržiūra – Kreditinės")
    st.dataframe(st.session_state["crn_norm"].head(20), use_container_width=True)
