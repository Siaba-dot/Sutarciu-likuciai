import streamlit as st
import pandas as pd
import numpy as np
import re
from datetime import date

st.header("📥 Įkėlimas")

st.write("**Sąskaitos.xlsx** – A: Data, D: Klientas, E: Pastabos, F: Sutartis (jei yra), **G: Suma su PVM**, 7: Valiuta")
inv_file = st.file_uploader("Įkelk Sąskaitos.xlsx", type=["xlsx"], key="inv")

st.write("**Kreditines.xlsx** – A: Data, B: Kreditinės Nr., D: Klientas, E: Pastabos, **F: Suma su PVM**, 6: Valiuta")
crn_file = st.file_uploader("Įkelk Kreditines.xlsx", type=["xlsx"], key="crn")

colF1, colF2 = st.columns(2)
with colF1:
    date_from = st.date_input("Laikotarpis nuo", value=date(date.today().year, 1, 1), key="date_from")
with colF2:
    date_to = st.date_input("Laikotarpis iki", value=date.today(), key="date_to")

@st.cache_data
def read_excel(file, sheet=0):
    return pd.read_excel(file, sheet_name=sheet, header=None, engine="openpyxl")

PAT = re.compile(r'(CA-\d{6}|CPO\d{5,}|ST-\d{2,}|\d{6,}/\d+/CA-\d{6}|[A-Z]{1,4}-\d{2,})')

def extract_contract(txt: str):
    if pd.isna(txt): return None
    m = PAT.search(str(txt))
    return m.group(0) if m else None

if inv_file:
    raw = read_excel(inv_file)
    inv = pd.DataFrame({
        "Data": pd.to_datetime(raw[0], errors="coerce"),
        "SaskaitosNr": raw[1].astype(str),
        "Klientas": raw[3].astype(str),
        "Pastabos": raw[4].astype(str),
        "Sutarties_raw": raw[5],
        "Suma_su_PVM": pd.to_numeric(raw[6], errors="coerce"),
        "Valiuta": raw[7]
    })
    inv = inv[(inv["Valiuta"]=="EUR") & inv["Data"].notna()].copy()
    inv["SutartiesID"] = inv["Sutarties_raw"].astype(str).apply(extract_contract)
    inv.loc[inv["SutartiesID"].isna(), "SutartiesID"] = inv["Pastabos"].apply(extract_contract)
    inv = inv[(inv["Data"].dt.date >= date_from) & (inv["Data"].dt.date <= date_to)].copy()
    # Tipų ir tarpų sanitarija
    inv["Klientas"] = inv["Klientas"].astype(str).str.strip()
    inv["SutartiesID"] = inv["SutartiesID"].astype(str).str.strip()
    st.subheader("Sąskaitos (filtruotos, SUMOS SU PVM)")
    st.dataframe(inv.head(100), use_container_width=True)
    st.session_state["inv_norm"] = inv

if crn_file:
    raw = read_excel(crn_file)
    crn = pd.DataFrame({
        "Data": pd.to_datetime(raw[0], errors="coerce"),
        "KreditinesNr": raw[1].astype(str),
        "Klientas": raw[3].astype(str),
        "Pastabos": raw[4].astype(str),
        "Suma_su_PVM": pd.to_numeric(raw[5], errors="coerce"),
        "Valiuta": raw[6]
    })
    crn = crn[(crn["Valiuta"]=="EUR") & crn["Data"].notna()].copy()
    crn["SutartiesID"] = crn["Pastabos"].apply(extract_contract)
    # Kreditinių sumas darome neigiamas (SU PVM)
    crn["Suma_su_PVM"] = -crn["Suma_su_PVM"].astype(float)
    crn = crn[(crn["Data"].dt.date >= date_from) & (crn["Data"].dt.date <= date_to)].copy()
    crn["Klientas"] = crn["Klientas"].astype(str).str.strip()
    crn["SutartiesID"] = crn["SutartiesID"].astype(str).str.strip()
    st.subheader("Kreditinės (filtruotos, SUMOS SU PVM)")
    st.dataframe(crn.head(100), use_container_width=True)
    st.session_state["crn_norm"] = crn

st.info("Perjunk į **🧾 Likučiai ir planai** bei **📈 MoM/WoW** kai failai įkelti.")
