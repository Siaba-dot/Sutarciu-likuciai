import streamlit as st

import pandas as pd
import numpy as np
from io import BytesIO
from decimal import Decimal, ROUND_DOWN
from datetime import date
import re

# =================== Puslapio nustatymas ===================
st.set_page_config(layout="wide")
st.markdown("## 💳 Kreditinių sąrašas (sumos SU PVM) – be susiejimo")

# Kompaktesnis išdėstymas
st.markdown("""
<style>
section.main > div { padding-top: 0rem; }
.block-container { padding-top: 0.5rem; padding-bottom: 0.5rem; }
</style>
""", unsafe_allow_html=True)

# =================== Pagalbinės ===================
def floor2(x):
    """Nukerpa iki 2 skaičių po kablelio (be apvalinimo)."""
    try:
        return float(Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_DOWN))
    except Exception:
        return 0.0

def ensure_df(src):
    return src if isinstance(src, pd.DataFrame) else None

def get_min_max_date(*dfs):
    dates = pd.concat([d["Data"] for d in dfs if d is not None and "Data" in d.columns], axis=0)
    dates = pd.to_datetime(dates, errors="coerce").dropna()
    if dates.empty:
        today = pd.Timestamp.today().normalize()
        return today, today
    return dates.min().normalize(), dates.max().normalize()

def safe_sheet_name(name: str, fallback: str = "Sheet1") -> str:
    name = "" if name is None else str(name)
    name = re.sub(r'[:\\/*?\[\]]', "_", name).strip()
    return (name or fallback)[:31]

def safe_filename(name: str, max_len: int = 150) -> str:
    name = "" if name is None else str(name)
    name = re.sub(r'[\\/:*?"<>|\r\n]+', "_", name).strip(" .")
    return (name or "export")[:max_len]

# LT/EU sumų parse (kablelis, NBSP, €, U+2212)
def parse_eur_robust(series):
    if series is None:
        return pd.Series(dtype=float)
    s = series.astype(str)
    s = s.str.replace('\u2212', '-', regex=False)  # minus U+2212 -> '-'
    s = s.str.replace('\u00A0', '', regex=False)   # NBSP lauk
    s = s.str.replace(' ', '', regex=False)        # tarpai lauk
    s = s.str.replace('€', '', regex=False)        # valiuta lauk
    s = s.str.replace(',', '.', regex=False)       # kablelis -> taškas
    s = s.str.replace(r'[^0-9\.\-]', '', regex=True)
    return pd.to_numeric(s, errors='coerce')

# Prievarta: kreditinių suma iš F kolonos (6-ta kolona)
def amount_from_F(df: pd.DataFrame) -> pd.Series:
    if df is None or df.empty:
        return pd.Series([], dtype=float)
    if df.shape[1] >= 6:
        return parse_eur_robust(df.iloc[:, 5]).fillna(0.0)
    # jei stulpelių < 6 – atsarginis (bandysim pavadintą stulpelį)
    return pd.Series([0.0] * len(df), index=df.index, dtype=float)

# Prefiksai kreditinių numeriams (atsarginis filtras, jei nėra "Tipas")
CREDIT_PREFIXES = ("COP", "KRE", "AAA")
CREDIT_RE = re.compile(r'^(?:' + '|'.join(CREDIT_PREFIXES) + r')[\s\-]*', re.IGNORECASE)
def is_credit_number(x: str) -> bool:
    return isinstance(x, str) and bool(CREDIT_RE.match(x.strip()))

# =================== Duomenys ===================
crn = ensure_df(st.session_state.get("crn_norm"))
if crn is None:
    st.warning("Įkelk kreditinių duomenis skiltyje **📥 Įkėlimas** (sesijos raktas: `crn_norm`).")
    st.stop()

# Tipų sanitarija (be susiejimų)
if "Data" in crn.columns:
    crn["Data"] = pd.to_datetime(crn["Data"], errors="coerce")
if "Klientas" in crn.columns:
    crn["Klientas"] = crn["Klientas"].astype(str).str.strip()
if "Saskaitos_NR" in crn.columns:
    crn["Saskaitos_NR"] = crn["Saskaitos_NR"].astype(str).str.strip().str.upper()
if "Pastabos" in crn.columns:
    crn["Pastabos"] = crn["Pastabos"].astype(str)
# Apsauga: jokių sumų į SutartiesID
if "SutartiesID" in crn.columns:
    crn["SutartiesID"] = crn["SutartiesID"].apply(lambda v: "" if pd.isna(v) else str(v)).str.strip()

# Paliekame TIK kreditines eilutes
if "Tipas" in crn.columns:
    mask_credit = crn["Tipas"].astype(str).str.lower().str.contains("kredit")
    crn = crn.loc[mask_credit].copy()
else:
    # atsarginis variantas, jei Tipas nėra
    if "Saskaitos_NR" in crn.columns:
        crn = crn.loc[crn["Saskaitos_NR"].astype(str).apply(is_credit_number)].copy()

# Užpildome Suma_su_PVM: pirmiausia F kolona, jei jos nėra – pavadintas stulpelis
crn["Suma_su_PVM"] = amount_from_F(crn)
if (crn["Suma_su_PVM"].abs() < 1e-12).all():
    # atsarginis – jei F fiziškai nėra/tuščia
    src = crn.get("Suma_su_PVM", crn.get("Suma", 0))
    crn["Suma_su_PVM"] = parse_eur_robust(src).fillna(0.0)

# =================== 📅 Laikotarpio filtras ===================
dmin, dmax = get_min_max_date(crn)
st.subheader("📅 Laikotarpio filtras")
rng = st.date_input(
    "Pasirink laikotarpį (nuo – iki)",
    value=(dmin.date(), dmax.date()),
    min_value=dmin.date(),
    max_value=max(dmax.date(), dmin.date()),
    format="YYYY-MM-DD",
)

if isinstance(rng, (tuple, list)) and len(rng) == 2:
    nuo, iki = rng
elif isinstance(rng, date):
    nuo, iki = rng, rng
else:
    nuo, iki = dmin.date(), dmax.date()

mask_crn = crn["Data"].dt.date.between(nuo, iki) if "Data" in crn.columns else pd.Series(True, index=crn.index)
crn_f = crn.loc[mask_crn].copy()

if crn_f.empty:
    st.info("Pasirinktame laikotarpyje kreditinių nėra.")
    st.stop()

# =================== Rodom ir eksportuojam TIK kreditines su sumomis ===================
# Skaičiai rodymui – nukerpam 2 sk.
crn_f["Suma_su_PVM"] = crn_f["Suma_su_PVM"].apply(floor2)

# KPI
total_kreditiniu = len(crn_f)
total_suma = float(crn_f["Suma_su_PVM"].sum())
c1, c2 = st.columns(2)
c1.metric("Kreditinių kiekis", f"{total_kreditiniu}")
c2.metric("Kreditinių suma (SU PVM)", f"{total_suma:,.2f} €")

# Lentelė
cols_order = [c for c in ["Data", "Saskaitos_NR", "Klientas", "Pastabos", "Suma_su_PVM", "Tipas"] if c in crn_f.columns]
st.subheader("📄 Kreditinių sąrašas (be susiejimo)")
st.dataframe(crn_f[cols_order].sort_values(["Data","Saskaitos_NR"]) if "Data" in cols_order else crn_f[cols_order],
             use_container_width=True)

# Eksportas
buf = BytesIO()
with pd.ExcelWriter(buf, engine="openpyxl") as xw:
    sheet = safe_sheet_name("Kreditines_SU_PVM")
    crn_f[cols_order].to_excel(xw, sheet_name=sheet, index=False)

st.download_button(
    "⬇️ Atsisiųsti kreditinių sąrašą (.xlsx)",
    data=buf.getvalue(),
    file_name=f"kreditines_SU_PVM__{nuo}_{iki}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)
