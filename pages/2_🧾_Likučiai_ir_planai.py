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

# =================== Kreditinių atpažinimas ===================
CREDIT_PREFIXES = ("COP", "KRE", "AAA")
CREDIT_RE = re.compile(r'^(?:' + '|'.join(CREDIT_PREFIXES) + r')[\s\-]*', re.IGNORECASE)

def is_credit_number(x: str) -> bool:
    return isinstance(x, str) and bool(CREDIT_RE.match(x.strip()))

# =================== TAISYKLĖ: VS/AAA ištrauka iš Pastabų ===================
def extract_last_vs_aaa(text: str) -> str:
    """
    - Ieško paskutinio 'VS' arba 'AAA' tekste.
    - Paimama nuo jo iki eilutės pabaigos.
    - Išvaloma į [A-Z0-9].
    - Jei neranda – grąžina tuščią.
    """
    if pd.isna(text):
        return ""
    s = str(text).upper()
    matches = list(re.finditer(r'(VS|AAA)', s))
    if not matches:
        return ""
    start = matches[-1].start()
    tail = s[start:]
    key = re.sub(r'[^A-Z0-9]', '', tail)
    return key

# =================== Kreditinių normalizatorius (jei ateina „žalias“) ===================
def normalize_credit_df_if_needed(crn_raw: pd.DataFrame | None) -> pd.DataFrame | None:
    if crn_raw is None or crn_raw.empty:
        return crn_raw

    cols = [c.lower() for c in crn_raw.columns.astype(str).tolist()]
    if set(["data", "saskaitos_nr"]).issubset(set(cols)):
        d = crn_raw.copy()
        d["Data"] = pd.to_datetime(d["Data"], errors="coerce")
        d["Suma_su_PVM"] = pd.to_numeric(d.get("Suma_su_PVM", 0), errors="coerce").fillna(0.0)
        if "Tipas" not in d.columns:
            d["Tipas"] = "Kreditinė"
        # Saugumas: jokios sumos niekada nerašom į SutartiesID
        if "SutartiesID" in d.columns:
            d["SutartiesID"] = d["SutartiesID"].astype(str).fillna("").str.strip()
        return d

    try:
        df = crn_raw.copy()
        pick = [0, 1, 3, 4, 5]  # A,B,D,E,F
        if df.shape[1] >= 6:
            df = df.iloc[:, pick]
        df.columns = ["Data", "Kreditines_NR", "Klientas", "Pastabos", "Suma_su_PVM"]

        df["Data"] = pd.to_datetime(df["Data"], errors="coerce")
        df["Suma_su_PVM"] = pd.to_numeric(df["Suma_su_PVM"], errors="coerce").fillna(0.0)
        df = df.dropna(how="all")

        mask_crn = df["Kreditines_NR"].astype(str).apply(is_credit_number)
        df = df.loc[mask_crn].copy()

        df = df.rename(columns={"Kreditines_NR": "Saskaitos_NR"})
        df["Saskaitos_NR"] = df["Saskaitos_NR"].astype(str).str.strip().str.upper()
        df["Klientas"] = df["Klientas"].astype(str).str.strip()
        df["Tipas"] = "Kreditinė"
        # Jokios sumos į SutartiesID!
        df["SutartiesID"] = ""  # apsauga
        return df.dropna(subset=["Data"]).reset_index(drop=True)
    except Exception:
        return crn_raw

# =================== Duomenys iš sesijos ===================
inv = ensure_df(st.session_state.get("inv_norm"))
crn = ensure_df(st.session_state.get("crn_norm"))

if inv is None:
    st.warning("Įkelk duomenis skiltyje **📥 Įkėlimas**.")
    st.stop()

# ===== Tipų sanitarija ir AIŠKIOS apsaugos nuo sumų patekimų į SutartiesID =====
for df in [inv, crn] if crn is not None else [inv]:
    df["Data"] = pd.to_datetime(df["Data"], errors="coerce")
    if "Klientas" in df.columns:
        df["Klientas"] = df["Klientas"].astype(str).str.strip()

    # Visada saugom SutartiesID kaip TEKSTĄ (jokių float, jokių sumų)
    if "SutartiesID" not in df.columns:
        df["SutartiesID"] = ""
    else:
        # jei kažkas įrašė skaičius/sumas – paversim į gryną tekstą ir nutrinsim tarpelius
        df["SutartiesID"] = df["SutartiesID"].apply(lambda v: "" if pd.isna(v) else str(v)).str.strip()

    # Suma_su_PVM – visada numeris
    df["Suma_su_PVM"] = pd.to_numeric(df.get("Suma_su_PVM", df.get("Suma", 0)), errors="coerce").fillna(0.0)

    if "Saskaitos_NR" in df.columns:
        df["Saskaitos_NR"] = df["Saskaitos_NR"].astype(str).str.strip().str.upper()
    if "Pastabos" in df.columns:
        df["Pastabos"] = df["Pastabos"].astype(str)

# Jei kreditinės dar „žalios“, normalizuojam
if crn is not None:
    crn = normalize_credit_df_if_needed(crn)

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

# =================== JoinKey kūrimas (pagal Pastabas: paskutinis VS/AAA) ===================
# INV pusė (išrašytos sąskaitos) – JoinKey iš jų numerio (jei numeris savyje turi VS/AAA uodegą)
inv_key = (
    inv[["Saskaitos_NR", "Klientas", "SutartiesID"]]
    .dropna(subset=["Saskaitos_NR"])
    .copy()
)
inv_key["Saskaitos_NR"] = inv_key["Saskaitos_NR"].astype(str).str.strip().str.upper()
inv_key["JoinKey"] = inv_key["Saskaitos_NR"].apply(extract_last_vs_aaa)
inv_key = inv_key.rename(columns={"Klientas": "Klientas_inv", "SutartiesID": "SutartiesID_inv"})

# SUSPAUDŽIAM iki unikalaus JoinKey -> fan-out FIX
inv_key = inv_key[inv_key["JoinKey"].astype(str).str.strip() != ""].copy()
inv_key_unique = (
    inv_key
    .sort_values(["Saskaitos_NR"])  # arba .sort_values(["SutartiesID"]) / ["Data"] jei patogiau
    .drop_duplicates(subset=["JoinKey"], keep="last")
    [["JoinKey", "Klientas_inv", "SutartiesID_inv"]]
)

# =================== Kreditinių susiejimas per Pastabas (JoinKey) ===================
if crn is not None:
    crn_work = crn.copy()

    # Paliekam tik tikras kreditines (pagal numerio prefiksus COP/KRE/AAA, jei turi numerį)
    if "Saskaitos_NR" in crn_work.columns:
        crn_work = crn_work[crn_work["Saskaitos_NR"].astype(str).apply(is_credit_number)].copy()

    # Kreditinėms JoinKey VISADA iš Pastabų (paskutinė VS/AAA)
    crn_work["JoinKey"] = crn_work.get("Pastabos", pd.Series(index=crn_work.index, dtype=str)).apply(extract_last_vs_aaa)

    # AIŠKI apsauga: NIEKADA nerašom sumų į SutartiesID
    crn_work["SutartiesID"] = ""  # ignoruojam bet ką, kas buvo

    # Sujungiame su unikaliu inv raktu – kad nebūtų daugiklio
    crn_work = crn_work.merge(
        inv_key_unique,
        on="JoinKey",
        how="left",
    )

    # FINAL laukus VISADA imame iš susietos išrašytos sąskaitos
    crn_work["Klientas_final"] = crn_work["Klientas_inv"]
    crn_work["SutartiesID_final"] = crn_work["SutartiesID_inv"].fillna("").astype(str).str.strip()

    # Datų filtras kreditinėms
    mask_crn = crn_work["Data"].dt.date.between(nuo, iki)
    crn_f = crn_work.loc[mask_crn].copy()
else:
    crn_f = None

# Jei viskas tuščia – baigiam
if inv_f.empty and (crn_f is None or crn_f.empty):
    st.info("Pasirinktame laikotarpyje duomenų nėra. Praplėsk datų intervalą.")
    st.stop()

# =================== Agregacijos (SU PVM) ===================
# 1) Išrašyta
inv_sum = (
    inv_f.groupby(["Klientas", "SutartiesID"], dropna=False)["Suma_su_PVM"]
    .sum()
    .rename("Israsyta")
    .reset_index()
)

# 2) Kreditinės (sumą rašome tik į Suma_su_PVM; jokių sumų į SutartiesID!)
if crn_f is not None and not crn_f.empty:
    # prievarta užtikrinam, kad kreditinių suma yra Suma_su_PVM ir niekur kitur
    crn_f["Suma_su_PVM"] = pd.to_numeric(crn_f["Suma_su_PVM"], errors="coerce").fillna(0.0)

    # Kredituota teigiamam rodymui, bet į faktą eis su minusu
    crn_f["Kredituota_pos"] = crn_f["Suma_su_PVM"].abs()
    crn_f["Kredituota_signed"] = -crn_f["Kredituota_pos"]

    # Agreguojam kreditus PRIE IŠRAŠYTOS SĄSKAITOS sutarties (tik jei sutartis rasta)
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

# 3) Sujungiame į faktą. Kredituota – šalia išrašytos sąskaitos.
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
out["Kredituota"] = out["Kredituota"].apply(floor2)  # teigiama
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

# =================== Diagnostika: kreditinių susiejimas ===================
if crn is not None:
    # po filtravimo
    crn_diag = crn_f if 'crn_f' in locals() and crn_f is not None else pd.DataFrame()
    if not crn_diag.empty:
        missing_map = crn_diag[
            (crn_diag["SutartiesID_final"].astype(str).str.strip() == "") |
            (crn_diag["JoinKey"].astype(str).str.strip() == "")
        ].copy()
        with st.expander("🔎 Kreditinių susiejimo diagnostika", expanded=False):
            st.write("Nesusietos kreditinės (neįtrauktos į sumas):")
            if missing_map.empty:
                st.success("Visos kreditinės susietos su išrašytomis sąskaitomis.")
            else:
                cols_diag = [
                    "Data", "Saskaitos_NR", "Klientas", "Pastabos",
                    "JoinKey", "Suma_su_PVM", "SutartiesID_final"
                ]
                show_diag = [c for c in cols_diag if c in missing_map.columns]
                st.dataframe(
                    missing_map[show_diag].sort_values("Data"),
                    use_container_width=True
                )
                st.info("Pastabose turi būti bent viena VS arba AAA seka; jei kelios – naudojama paskutinė.")

# =================== Eksportas – visa suvestinė (pagal laikotarpį) ===================
buf = BytesIO()
with pd.ExcelWriter(buf, engine="openpyxl") as xw:
    out.to_excel(xw, sheet_name="Sutarciu_likuciai_SU_PVM", index=False)
    inv_f.to_excel(xw, sheet_name="Saskaitos_ISRASYTA_SU_PVM", index=False)
    if 'crn_f' in locals() and crn_f is not None and not crn_f.empty:
        export_crn = crn_f.copy()
        export_crn.to_excel(xw, sheet_name="Kreditines_SU_PVM", index=False)

        # Papildomai – neužsirišusios kreditinės
        missing_map = crn_f[
            (crn_f["SutartiesID_final"].astype(str).str.strip() == "") |
            (crn_f["JoinKey"].astype(str).str.strip() == "")
        ].copy()
        if not missing_map.empty:
            missing_map.to_excel(xw, sheet_name="CRN_neuzrisa", index=False)

st.download_button(
    "⬇️ Eksportuoti suvestinę (.xlsx)",
    data=buf.getvalue(),
    file_name=f"sutarciu_likuciai_SU_PVM__{nuo}_{iki}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)
