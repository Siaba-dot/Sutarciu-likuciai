import streamlit as st

import pandas as pd
import numpy as np
from io import BytesIO
from decimal import Decimal, ROUND_DOWN
from datetime import date
import re

# =================== Puslapio nustatymas ===================
st.set_page_config(layout="wide")
st.markdown("## 🧾 Likučiai ir planai (sumos SU PVM)")

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
    if src is None:
        return None
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

# ======== Patikimas LT/EU sumų parse ========
def parse_eur_robust(series):
    """
    Konvertuoja LT/EU formatą į float:
    – pašalina NBSP, tarpus, €, '−' (U+2212) -> '-'; ',' -> '.'
    """
    if series is None:
        return pd.Series(dtype=float)
    s = series.astype(str)
    s = s.str.replace('\u2212', '-', regex=False)  # U+2212
    s = s.str.replace('\u00A0', '', regex=False)   # NBSP
    s = s.str.replace(' ', '', regex=False)
    s = s.str.replace('€', '', regex=False)
    s = s.str.replace(',', '.', regex=False)
    s = s.str.replace(r'[^0-9\.\-]', '', regex=True)
    return pd.to_numeric(s, errors='coerce')

# ======== Paprasti raktai susiejimui ========
def norm_alnum(x: str) -> str:
    """Palieka tik A-Z0-9 (susiejimo raktams)."""
    if pd.isna(x):
        return ""
    s = str(x).upper().strip()
    s = s.replace("–", "-").replace("—", "-")
    s = re.sub(r"\s+", "", s)
    return re.sub(r"[^A-Z0-9]", "", s)

def only_digits(x: str) -> str:
    if pd.isna(x):
        return ""
    return re.sub(r"[^0-9]", "", str(x))

def extract_last_from_notes(text: str) -> str:
    """
    PASKUTINĖ nuoroda iš Pastabų:
      1) paskutinė 'VS...' (su uodega),
      2) paskutinė 'AAA...' (su uodega),
      3) kitaip – paskutinė alfanumerinė su bent 1 skaitmeniu.
    Grąžina A-Z0-9.
    """
    if pd.isna(text):
        return ""
    s = str(text).upper().replace('\u00A0', ' ')
    candidates = []

    vs = re.findall(r'(VS[^\s]*)', s)
    if vs: candidates.extend(vs)

    aaa = re.findall(r'(AAA[^\s]*)', s)
    if aaa: candidates.extend(aaa)

    alnum = re.findall(r'([A-Z0-9][A-Z0-9\-/]*\d[A-Z0-9\-/]*)', s)
    if alnum: candidates.extend(alnum)

    if not candidates:
        return ""
    return norm_alnum(candidates[-1])

# =================== Duomenys iš sesijos ===================
inv = ensure_df(st.session_state.get("inv_norm"))
crn_raw = ensure_df(st.session_state.get("crn_norm"))

if inv is None:
    st.warning("Įkelk duomenis skiltyje **📥 Įkėlimas**.")
    st.stop()

# ===== Sanitarija (BENDRA) =====
for df in [inv, crn_raw] if crn_raw is not None else [inv]:
    if "Data" in df.columns:
        df["Data"] = pd.to_datetime(df["Data"], errors="coerce")
    if "Klientas" in df.columns:
        df["Klientas"] = df["Klientas"].astype(str).str.strip()
    # SutartiesID – tik tekstas
    if "SutartiesID" not in df.columns:
        df["SutartiesID"] = ""
    else:
        df["SutartiesID"] = df["SutartiesID"].apply(lambda v: "" if pd.isna(v) else str(v)).str.strip()
    if "Saskaitos_NR" in df.columns:
        df["Saskaitos_NR"] = df["Saskaitos_NR"].astype(str).str.strip().str.upper()
    if "Pastabos" in df.columns:
        df["Pastabos"] = df["Pastabos"].astype(str)

# ===== Išrašytų sumos =====
inv["Suma_su_PVM"] = parse_eur_robust(inv.get("Suma_su_PVM", inv.get("Suma", 0))).fillna(0.0)

# ===== Kreditinių – TIK  „Tipas = Kreditinė“  + sumos TIESIAI iš F (6 kolona) =====
if crn_raw is not None:
    crn = crn_raw.copy()

    # 1) paliekam TIK kreditines (nebe bus 3000+)
    if "Tipas" in crn.columns:
        mask_tip = crn["Tipas"].astype(str).str.strip().str.lower().str.contains("kredit")
        crn = crn.loc[mask_tip].copy()

    # 2) SUMA VISADA iš F kolonos (jei yra)
    if crn.shape[1] >= 6:
        crn["Suma_su_PVM"] = parse_eur_robust(crn.iloc[:, 5]).fillna(0.0)
    else:
        # atsarginis – jei failas su mažiau stulpelių
        crn["Suma_su_PVM"] = parse_eur_robust(crn.get("Suma_su_PVM", crn.get("Suma", 0))).fillna(0.0)

    # 3) NIEKADA nenaudojam kreditinės SutartiesID
    crn["SutartiesID"] = ""

else:
    crn = None

# =================== 📅 Laikotarpio filtras ===================
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

mask_inv = inv["Data"].dt.date.between(nuo, iki)
inv_f = inv.loc[mask_inv].copy()

# =================== INV raktai (unikalizuoti) ===================
inv_key = (
    inv[["Data", "Saskaitos_NR", "Klientas", "SutartiesID"]]
    .dropna(subset=["Saskaitos_NR"])
    .copy()
)

# Jei pačiame invoiso numeryje yra VS/AAA – imame; kitaip – visas numeris (A-Z0-9)
def extract_from_number(nr: str) -> str:
    if pd.isna(nr): return ""
    s = str(nr).upper()
    m = re.search(r'(VS[^\s]+)$', s) or re.search(r'(AAA[^\s]+)$', s)
    return norm_alnum(m.group(1)) if m else norm_alnum(s)

inv_key["Key_inv_best"] = inv_key["Saskaitos_NR"].apply(extract_from_number)
inv_key["Key_inv_digits"] = inv_key["Key_inv_best"].apply(only_digits)
inv_key = inv_key.rename(columns={"Klientas": "Klientas_inv", "SutartiesID": "SutartiesID_inv"})

# many-to-one: vienas raktas -> vienas įrašas (vėliausia sąskaita pagal datą)
inv_key = inv_key.sort_values(["Data", "Saskaitos_NR"])
inv_key = inv_key[inv_key["Key_inv_best"].astype(str).str.strip() != ""].copy()
inv_key_unique = (
    inv_key
    .drop_duplicates(subset=["Key_inv_best"], keep="last")
    [["Key_inv_best", "Key_inv_digits", "Klientas_inv", "SutartiesID_inv"]]
)

# =================== CRN susiejimas (iš Pastabų) ===================
if crn is not None and not crn.empty:
    crn_work = crn.copy()
    # Raktas VISADA iš Pastabų
    crn_work["Key_crn"] = crn_work.get("Pastabos", pd.Series(index=crn_work.index, dtype=str)).apply(extract_last_from_notes)
    crn_work["Key_crn_digits"] = crn_work["Key_crn"].apply(only_digits)

    # 1) jungimas per alfanumerinį raktą
    crn_work = crn_work.merge(
        inv_key_unique,
        left_on="Key_crn",
        right_on="Key_inv_best",
        how="left",
    )

    # 2) fallback jungimas – tik skaitmenimis (kur dar nesusieta)
    mask_unmatched = crn_work["SutartiesID_inv"].isna() | (crn_work["SutartiesID_inv"].astype(str).str.strip() == "")
    if mask_unmatched.any():
        inv_digits_map = inv_key_unique[["Key_inv_digits", "Klientas_inv", "SutartiesID_inv"]].drop_duplicates(subset=["Key_inv_digits"])
        crn_work.loc[mask_unmatched, ["Klientas_inv", "SutartiesID_inv"]] = crn_work.loc[mask_unmatched].merge(
            inv_digits_map,
            left_on="Key_crn_digits",
            right_on="Key_inv_digits",
            how="left"
        )[["Klientas_inv_y", "SutartiesID_inv_y"]].values

    # FINAL – VISADA iš IŠRAŠYTOS
    crn_work["Klientas_final"] = crn_work["Klientas_inv"]
    crn_work["SutartiesID_final"] = crn_work["SutartiesID_inv"].fillna("").astype(str).str.strip()

    # Laikotarpio filtras kreditinėms
    mask_crn = crn_work["Data"].dt.date.between(nuo, iki)
    crn_f = crn_work.loc[mask_crn].copy()
else:
    crn_f = None

# ===== Informacinės eilutės (po filtrų turi matytis ~18 kreditinių) =====
if crn is not None:
    st.caption(f"💳 Kreditinių eilučių iš įkėlimo: {len(crn)} | Bendra suma (visų): {crn['Suma_su_PVM'].sum():,.2f}")
if crn_f is not None and not crn_f.empty:
    st.caption(f"📆 Kreditinių suma laikotarpyje: {crn_f['Suma_su_PVM'].sum():,.2f} | Eilučių: {len(crn_f)}")

# =================== Jei viskas tuščia – stabdom ===================
if inv_f.empty and (crn_f is None or crn_f.empty):
    st.info("Pasirinktame laikotarpyje duomenų nėra. Praplėsk datų intervalą.")
    st.stop()

# =================== Agregacijos (SU PVM) ===================
# Išrašytos
inv_sum = (
    inv_f.groupby(["Klientas", "SutartiesID"], dropna=False)["Suma_su_PVM"]
    .sum()
    .rename("Israsyta")
    .reset_index()
)

# Kreditinės (į Faktą eis su minusu). Agreguojame TIK susietas su sutartimi.
if crn_f is not None and not crn_f.empty:
    crn_f["Suma_su_PVM"] = crn_f["Suma_su_PVM"].astype(float).fillna(0.0)
    crn_f["Kredituota_pos"] = crn_f["Suma_su_PVM"].abs()
    crn_f["Kredituota_signed"] = -crn_f["Kredituota_pos"]

    crn_ok = crn_f[crn_f["SutartiesID_final"].astype(str).str.strip() != ""].copy()

    crn_sum_signed = (
        crn_ok.groupby(["Klientas_final", "SutartiesID_final"], dropna=False)["Kredituota_signed"]
        .sum()
        .reset_index()
        .rename(columns={"Klientas_final": "Klientas", "SutartiesID_final": "SutartiesID"})
    )
    crn_sum = crn_sum_signed.copy()
    crn_sum["Kredituota"] = crn_sum["Kredituota_signed"].abs()
    crn_sum = crn_sum.drop(columns=["Kredituota_signed"])
else:
    crn_sum_signed = pd.DataFrame(columns=["Klientas", "SutartiesID", "Kredituota_signed"])
    crn_sum = pd.DataFrame(columns=["Klientas", "SutartiesID", "Kredituota"])

# Sujungiame
fact = pd.merge(inv_sum, crn_sum, how="outer", on=["Klientas", "SutartiesID"]).fillna(0.0)
fact = pd.merge(
    fact,
    crn_sum_signed.rename(columns={"Kredituota_signed": "Kredituota_signed"}),
    how="left",
    on=["Klientas", "SutartiesID"],
).fillna({"Kredituota_signed": 0.0})

# Faktas = Išrašyta - Kredituota
fact["Faktas"] = fact["Israsyta"] + fact["Kredituota_signed"]

# =================== REDAGUOJAMI PLANAI ===================
if "plans" not in st.session_state:
    st.session_state["plans"] = pd.DataFrame(columns=["Klientas", "SutartiesID", "SutartiesPlanas"])

base = fact[["Klientas", "SutartiesID"]].drop_duplicates().copy()
plans_old = st.session_state["plans"][["Klientas", "SutartiesID", "SutartiesPlanas"]] if not st.session_state["plans"].empty else None
if plans_old is not None and not plans_old.empty:
    plans = pd.merge(base, plans_old, how="left", on=["Klientas", "SutartiesID"])
else:
    plans = base.copy()
    plans["SutartiesPlanas"] = 0.0

plans["SutartiesPlanas"] = pd.to_numeric(plans["SutartiesPlanas"], errors="coerce").fillna(0.0)

st.subheader("✍️ Įvesk sutarčių planus (SU PVM)")
plans = st.data_editor(
    plans.sort_values(["Klientas", "SutartiesID"]).reset_index(drop=True),
    num_rows="dynamic",
    hide_index=True,
    use_container_width=True,
    disabled=False,
    key="plans_editor",
    column_config={
        "Klientas": st.column_config.TextColumn(disabled=True),
        "SutartiesID": st.column_config.TextColumn(disabled=True),
        "SutartiesPlanas": st.column_config.NumberColumn(
            "Sutarties suma (planas) €", step=0.01, format="%.2f",
            help="Įvesk planą SU PVM (nukirpimas iki 2 skaitmenų, be apvalinimo)"
        ),
    },
)
plans["Klientas"] = plans["Klientas"].astype(str).str.strip()
plans["SutartiesID"] = plans["SutartiesID"].astype(str).str.strip()
st.session_state["plans"] = plans

# =================== Likučiai ===================
out = pd.merge(plans, fact, how="left", on=["Klientas", "SutartiesID"]).fillna(0.0)
out["Israsyta"] = out["Israsyta"].apply(floor2)
out["Kredituota"] = out["Kredituota"].apply(floor2)
out["Faktas"] = out["Faktas"].apply(floor2)
out["Like"] = (out["SutartiesPlanas"] - out["Faktas"]).apply(floor2)

# =================== KPI ===================
total_planas = floor2(out["SutartiesPlanas"].sum())
total_israsyta = floor2(out["Israsyta"].sum())
total_kred = floor2(out["Kredituota"].sum())
total_faktas = floor2(out["Faktas"].sum())
total_like = floor2(total_planas - total_faktas)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Išrašyta € (su PVM)", f"{total_israsyta:,.2f}")
c2.metric("Kredituota € (su PVM)", f"{total_kred:,.2f}")
c3.metric("Faktas € (su PVM)", f"{total_faktas:,.2f}")
c4.metric("Likutis € (su PVM)", f"{total_like:,.2f}")

# =================== Progreso juosta ===================
def progress_bar(p: float) -> str:
    p = 0.0 if pd.isna(p) else float(p)
    p = max(0.0, p)
    blocks = int(min(100.0, p) // 5)
    return "█" * blocks + "░" * (20 - blocks) + f"  {p:.1f}%"

den = out["SutartiesPlanas"].replace(0, np.nan)
out["PctIsnaudota"] = np.where(den.isna(), 0.0, (out["Faktas"] / den) * 100.0)
out["PctIsnaudota"] = out["PctIsnaudota"].clip(lower=0, upper=999)
out["Progresas"] = out["PctIsnaudota"].apply(progress_bar)

# =================== Pagrindinė lentelė ===================
st.subheader("Sutarčių likučiai (SU PVM)")
cols_order = [
    "Klientas",
    "SutartiesID",
    "SutartiesPlanas",
    "Israsyta",
    "Kredituota",
    "Faktas",
    "Like",
    "PctIsnaudota",
    "Progresas",
]
show_cols = [c for c in cols_order if c in out.columns]
st.dataframe(out[show_cols].sort_values(["Klientas", "SutartiesID"]), use_container_width=True)

# =================== Diagnostika (turi matytis ~18 kreditinių po filtro) ===================
st.divider()
st.subheader("🔎 Diagnostika (kreditinės)")
if crn is not None and crn_f is not None and not crn_f.empty:
    st.write(f"💳 Kreditinių laikotarpyje: **{len(crn_f)}** (iš įkeltų: {len(crn)})")
    zeros = (crn_f["Suma_su_PVM"].abs() < 1e-12).sum()
    if zeros > 0:
        st.error(f"⚠️ 0 sumos kreditinių eilučių: {zeros}. Sumos imamos iš **F** kolonos – patikrink šaltinį.")
    with st.expander("Pavyzdžiai (Pastabos → raktas → sutartis → suma):", expanded=False):
        cols_dbg = [c for c in ["Data","Saskaitos_NR","Pastabos","Key_crn","SutartiesID_final","Suma_su_PVM"] if c in crn_f.columns]
        st.dataframe(crn_f[cols_dbg].head(30), use_container_width=True)

# =================== Eksportas ===================
buf = BytesIO()
with pd.ExcelWriter(buf, engine="openpyxl") as xw:
    out.to_excel(xw, sheet_name="Sutarciu_likuciai_SU_PVM", index=False)
    inv_f.to_excel(xw, sheet_name="Saskaitos_ISRASYTA_SU_PVM", index=False)
    if crn_f is not None and not crn_f.empty:
        crn_f.to_excel(xw, sheet_name="Kreditines_SU_PVM", index=False)

st.download_button(
    "⬇️ Eksportuoti suvestinę (.xlsx)",
    data=buf.getvalue(),
    file_name=f"sutarciu_likuciai_SU_PVM__{nuo}_{iki}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)
