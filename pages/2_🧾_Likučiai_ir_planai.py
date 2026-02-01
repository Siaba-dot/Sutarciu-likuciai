
   import streamlit as st
import pandas as pd
import numpy as np
from io import BytesIO
from decimal import Decimal, ROUND_DOWN
from datetime import date
import re

# =================== Puslapis ===================
st.set_page_config(layout="wide")
st.markdown("## 🧾 Išrašytos ir kreditinės (SU PVM) – be susiejimų, be nulinių sumų")

st.markdown("""
<style>
section.main > div { padding-top: 0rem; }
.block-container { padding-top: 0.5rem; padding-bottom: 0.75rem; }
</style>
""", unsafe_allow_html=True)

# =================== Pagalbinės ===================
def floor2(x):
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

# LT/EU parse – vienoda tiek išrašytoms, tiek kreditinėms
def parse_eur_robust(series):
    if series is None:
        return pd.Series(dtype=float)
    s = series.astype(str)
    s = s.str.replace('\u2212', '-', regex=False)  # netikras minusas U+2212 -> '-'
    s = s.str.replace('\u00A0', '', regex=False)   # NBSP lauk
    s = s.str.replace(' ', '', regex=False)        # tarpai lauk
    s = s.str.replace('€', '', regex=False)        # valiuta lauk
    s = s.str.replace(',', '.', regex=False)       # kablelis -> taškas
    s = s.str.replace(r'[^0-9\.\-]', '', regex=True)
    return pd.to_numeric(s, errors='coerce')

# Tikros kreditinės pagal prefiksą
CREDIT_RE = re.compile(r'^(COP|KRE|AAA)', re.IGNORECASE)
def is_credit_number(x: str) -> bool:
    return isinstance(x, str) and bool(CREDIT_RE.match(x.strip()))

# =================== Duomenys ===================
inv = ensure_df(st.session_state.get("inv_norm"))
crn = ensure_df(st.session_state.get("crn_norm"))

if inv is None:
    st.warning("Įkelk **išrašytas sąskaitas** (`inv_norm`) skiltyje **📥 Įkėlimas**.")
    st.stop()

# Bendra sanitarija
for df in [inv, crn] if crn is not None else [inv]:
    if "Data" in df.columns:
        df["Data"] = pd.to_datetime(df["Data"], errors="coerce")
    if "Klientas" in df.columns:
        df["Klientas"] = df["Klientas"].astype(str).str.strip()
    if "Saskaitos_NR" in df.columns:
        df["Saskaitos_NR"] = df["Saskaitos_NR"].astype(str).str.strip().str.upper()
    if "Pastabos" in df.columns:
        df["Pastabos"] = df["Pastabos"].astype(str)
    if "SutartiesID" not in df.columns:
        df["SutartiesID"] = ""
    else:
        df["SutartiesID"] = df["SutartiesID"].apply(lambda v: "" if pd.isna(v) else str(v)).str.strip()

# ===== IŠRAŠYTOS: sumos iš `Suma_su_PVM` (ar `Suma`) =====
if "Suma_su_PVM" not in inv.columns and "Suma" not in inv.columns:
    st.error("Išrašytų faile nerasta nei `Suma_su_PVM`, nei `Suma`.")
    st.stop()
inv["Suma_su_PVM"] = parse_eur_robust(inv.get("Suma_su_PVM", inv.get("Suma", 0))).fillna(0.0)

# ===== KREDITINĖS: ta pati logika + prefiksų filtras =====
if crn is not None and not crn.empty:
    crn = crn.copy()

    # Paliekam tik kreditines pagal numerį COP|KRE|AAA
    if "Saskaitos_NR" not in crn.columns:
        st.error("Kreditinių faile nėra `Saskaitos_NR` (būtinai reikia COP/KRE/AAA filtrui).")
        st.stop()
    crn = crn.loc[crn["Saskaitos_NR"].astype(str).apply(is_credit_number)].copy()

    if crn.empty:
        crn_f = crn
    else:
        if "Suma_su_PVM" not in crn.columns and "Suma" not in crn.columns:
            st.error("Kreditinių faile nerasta nei `Suma_su_PVM`, nei `Suma`. Stulpelis PRIVALO būti.")
            st.stop()

        crn["Suma_su_PVM"] = parse_eur_robust(crn.get("Suma_su_PVM", crn.get("Suma", 0)))

        # Griežta kontrolė: nė viena kreditinė neturi būti 0/NaN
        bad = crn[crn["Suma_su_PVM"].isna() | (crn["Suma_su_PVM"] == 0)]
        if not bad.empty:
            st.error("⚠️ Rasta kreditinių su tuščia/0 `Suma_su_PVM`. Kadangi 'negali būti 0', ištaisyk šaltinyje. Žemiau problematiškos eilutės:")
            show = [c for c in ["Data","Saskaitos_NR","Klientas","Pastabos","Suma_su_PVM"] if c in bad.columns]
            st.dataframe(bad[show].head(50), use_container_width=True)
            st.stop()
else:
    crn_f = None

# =================== Laikotarpio filtras ===================
dmin, dmax = get_min_max_date(inv, crn)
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

mask_inv = inv["Data"].dt.date.between(nuo, iki) if "Data" in inv.columns else pd.Series(True, index=inv.index)
inv_f = inv.loc[mask_inv].copy()

if crn is not None:
    mask_crn = crn["Data"].dt.date.between(nuo, iki) if "Data" in crn.columns else pd.Series(True, index=crn.index)
    crn_f = crn.loc[mask_crn].copy()
else:
    crn_f = None

# =================== Išrašytos (planai ir likučiai – kaip visada) ===================
st.divider()
st.subheader("📄 Išrašytos sąskaitos (SU PVM) – planai ir likučiai")

inv_sum = (
    inv_f.groupby(["Klientas", "SutartiesID"], dropna=False)["Suma_su_PVM"]
    .sum()
    .rename("Israsyta")
    .reset_index()
)

# Planai (redaguojami)
if "plans" not in st.session_state:
    st.session_state["plans"] = pd.DataFrame(columns=["Klientas", "SutartiesID", "SutartiesPlanas"])

base = inv_sum[["Klientas", "SutartiesID"]].drop_duplicates().copy()
plans_old = st.session_state["plans"][["Klientas", "SutartiesID", "SutartiesPlanas"]] if not st.session_state["plans"].empty else None
if plans_old is not None and not plans_old.empty:
    plans = pd.merge(base, plans_old, how="left", on=["Klientas", "SutartiesID"])
else:
    plans = base.copy(); plans["SutartiesPlanas"] = 0.0

plans["SutartiesPlanas"] = pd.to_numeric(plans["SutartiesPlanas"], errors="coerce").fillna(0.0)
st.markdown("### ✍️ Įvesk sutarčių planus (SU PVM)")
plans = st.data_editor(
    plans.sort_values(["Klientas","SutartiesID"]).reset_index(drop=True),
    num_rows="dynamic", hide_index=True, use_container_width=True, key="plans_editor",
    column_config={
        "Klientas": st.column_config.TextColumn(disabled=True),
        "SutartiesID": st.column_config.TextColumn(disabled=True),
        "SutartiesPlanas": st.column_config.NumberColumn("Sutarties suma (planas) €", step=0.01, format="%.2f"),
    },
)
plans["Klientas"] = plans["Klientas"].astype(str).str.strip()
plans["SutartiesID"] = plans["SutartiesID"].astype(str).str.strip()
st.session_state["plans"] = plans

# Suvestinė be kreditinių įtakos (pagal nutylėjimą)
out = pd.merge(plans, inv_sum, how="left", on=["Klientas","SutartiesID"]).fillna({"Israsyta":0.0})
out["Israsyta"] = out["Israsyta"].apply(floor2)
out["Faktas"] = out["Israsyta"]
out["Like"]  = (out["SutartiesPlanas"] - out["Faktas"]).apply(floor2)

# =================== Kreditinių sąrašas (be susiejimų) ===================
st.divider()
st.subheader("💳 Kreditinės (SU PVM) – TIK `COP|KRE|AAA`, tokia pati sumų logika kaip išrašytoms")

total_kred = 0.0
if crn_f is None or crn_f.empty:
    st.info("Pasirinktame laikotarpyje **kreditinių nėra**.")
else:
    crn_f["Suma_su_PVM"] = crn_f["Suma_su_PVM"].astype(float).fillna(0.0).apply(floor2)
    total_kred = float(crn_f["Suma_su_PVM"].sum())
    cols_crn = [c for c in ["Data","Saskaitos_NR","Klientas","Pastabos","Suma_su_PVM"] if c in crn_f.columns]
    st.dataframe(
        crn_f[cols_crn].sort_values(["Data","Saskaitos_NR"]) if "Data" in cols_crn else crn_f[cols_crn],
        use_container_width=True
    )

c1, c2, c3 = st.columns(3)
c1.metric("Kreditinių kiekis", "0" if crn_f is None else f"{len(crn_f)}")
c2.metric("Kreditinių suma (SU PVM)", f"{total_kred:,.2f} €")
c3.metric("Filtras", "COP | KRE | AAA")

# =================== KPI ir Likučiai (be kreditinių) ===================
st.divider()
st.subheader("📊 Sutarčių likučiai (SU PVM) – be kreditinių įtakos")

total_planas = floor2(out["SutartiesPlanas"].sum())
total_israsyta = floor2(out["Israsyta"].sum())
total_faktas = floor2(out["Faktas"].sum())
total_like = floor2(total_planas - total_faktas)

c1, c2, c3 = st.columns(3)
c1.metric("Išrašyta € (SU PVM)", f"{total_israsyta:,.2f}")
c2.metric("Faktas € (SU PVM)", f"{total_faktas:,.2f}")
c3.metric("Likutis € (SU PVM)", f"{total_like:,.2f}")

# Progreso juosta
def progress_bar(p: float) -> str:
    p = 0.0 if pd.isna(p) else float(p)
    p = max(0.0, p)
    blocks = int(min(100.0, p) // 5)
    return "█" * blocks + "░" * (20 - blocks) + f"  {p:.1f}%"

den = out["SutartiesPlanas"].replace(0, np.nan)
out["PctIsnaudota"] = np.where(den.isna(), 0.0, (out["Faktas"] / den) * 100.0)
out["PctIsnaudota"] = out["PctIsnaudota"].clip(lower=0, upper=999)
out["Progresas"] = out["PctIsnaudota"].apply(progress_bar)

cols_order = ["Klientas","SutartiesID","SutartiesPlanas","Israsyta","Faktas","Like","PctIsnaudota","Progresas"]
show_cols = [c for c in cols_order if c in out.columns]
st.dataframe(out[show_cols].sort_values(["Klientas","SutartiesID"]), use_container_width=True)

# =================== Eksportas ===================
buf_all = BytesIO()
with pd.ExcelWriter(buf_all, engine="openpyxl") as xw:
    out[show_cols].to_excel(xw, sheet_name="Sutarciu_likuciai_SU_PVM", index=False)
    inv_f.to_excel(xw, sheet_name="Saskaitos_ISRASYTA_SU_PVM", index=False)
    if crn_f is not None and not crn_f.empty:
        crn_cols = [c for c in ["Data","Saskaitos_NR","Klientas","Pastabos","Suma_su_PVM"] if c in crn_f.columns]
        crn_f[crn_cols].to_excel(xw, sheet_name="Kreditines_SU_PVM", index=False)

st.download_button(
    "⬇️ Eksportuoti suvestinę (.xlsx)",
    data=buf_all.getvalue(),
    file_name=f"sutarciu_ir_kreditiniu_suvestine__{nuo}_{iki}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)
