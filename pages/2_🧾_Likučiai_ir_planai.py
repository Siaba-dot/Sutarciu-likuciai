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

# ===== Saugus LT/EU sumų parse (nebeliks 0 dėl formato) =====
def parse_eur_robust(series):
    """
    Patikimai paverčia LT/EU formatu pateiktas sumas į float:
    – pašalina NBSP, tarpus, €, kitus simbolius;
    – '−' (U+2212) -> '-';
    – ',' -> '.'.
    """
    if series is None:
        return pd.Series(dtype=float)
    s = series.astype(str)
    s = s.str.replace('\u2212', '-', regex=False)              # U+2212 -> '-'
    s = s.str.replace('\u00A0', '', regex=False)               # NBSP lauk
    s = s.str.replace(' ', '', regex=False)                    # tarpai lauk
    s = s.str.replace('€', '', regex=False)                    # valiuta lauk
    s = s.str.replace(',', '.', regex=False)                   # kablelis -> taškas
    s = s.str.replace(r'[^0-9\.\-]', '', regex=True)           # tik 0-9 . -
    return pd.to_numeric(s, errors='coerce')

# ===== Normalizavimai raktams =====
def norm_alnum(x: str) -> str:
    """Paverčia į A-Z0-9 (pašalina tarpus, brūkšnius, simbolius)."""
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

def extract_last_invoice_ref(text: str) -> str:
    """
    Paima PASKUTINĘ nuorodą į išrašytą sąskaitą iš Pastabų:
      1) jei yra VS... -> paima paskutinę VS-seką su uodega,
      2) jei yra AAA... -> paima paskutinę AAA-seką su uodega,
      3) kitaip paima paskutinę ALFANUM seką, kuri turi bent 1 skaitmenį (pvz. SF-2024-0012, PV-12345, INV0007),
      4) jei neranda – paima paskutinę skaitmenų seką (>=5),
      5) viską išvalo į A-Z0-9.
    """
    if pd.isna(text):
        return ""
    s = str(text).upper().replace('\u00A0', ' ')
    candidates = []

    # 1) paskutinis VS...
    vs = re.findall(r'(VS[^\s]*)', s)
    if vs: candidates.extend(vs)

    # 2) paskutinis AAA...
    aaa = re.findall(r'(AAA[^\s]*)', s)
    if aaa: candidates.extend(aaa)

    # 3) paskutinė alfanumerinė su bent 1 skaitmeniu (raidės/skaičiai/brūkšniai/slash)
    alnum = re.findall(r'([A-Z0-9][A-Z0-9\-/]*\d[A-Z0-9\-/]*)', s)
    if alnum: candidates.extend(alnum)

    # 4) paskutinė ilgesnė skaitmenų seka
    digits = re.findall(r'(\d{5,})', s)
    if digits: candidates.extend(digits)

    if not candidates:
        return ""
    last = candidates[-1]
    return norm_alnum(last)

# =================== Duomenų paruošimas ===================
inv = ensure_df(st.session_state.get("inv_norm"))
crn = ensure_df(st.session_state.get("crn_norm"))

if inv is None:
    st.warning("Įkelk duomenis skiltyje **📥 Įkėlimas**.")
    st.stop()

# Tipų sanitarija ir aiškios apsaugos
for df in [inv, crn] if crn is not None else [inv]:
    df["Data"] = pd.to_datetime(df["Data"], errors="coerce")
    if "Klientas" in df.columns:
        df["Klientas"] = df["Klientas"].astype(str).str.strip()
    # SutartiesID – visada tekstas
    if "SutartiesID" not in df.columns:
        df["SutartiesID"] = ""
    else:
        df["SutartiesID"] = df["SutartiesID"].apply(lambda v: "" if pd.isna(v) else str(v)).str.strip()
    # Sumos
    df["Suma_su_PVM"] = parse_eur_robust(df.get("Suma_su_PVM", df.get("Suma", 0))).fillna(0.0)
    # Numeriai ir pastabos
    if "Saskaitos_NR" in df.columns:
        df["Saskaitos_NR"] = df["Saskaitos_NR"].astype(str).str.strip().str.upper()
    if "Pastabos" in df.columns:
        df["Pastabos"] = df["Pastabos"].astype(str)

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

# =================== INV raktai (išrašytoms) ===================
inv_key = (
    inv[["Data", "Saskaitos_NR", "Klientas", "SutartiesID"]]
    .dropna(subset=["Saskaitos_NR"])
    .copy()
)

# Geriausias raktas invoisams:
# - pirma bandome ištraukti VS/AAA iš paties numerio,
# - jei nėra — naudojame visą numerį sutvarkytą į A-Z0-9.
inv_key["Key_inv_vsaaa"] = inv_key["Saskaitos_NR"].apply(extract_last_invoice_ref := extract_last_invoice_ref)
inv_key["Saskaitos_NR_norm"] = inv_key["Saskaitos_NR"].apply(norm_alnum)
inv_key["Key_inv_best"] = np.where(
    inv_key["Key_inv_vsaaa"].astype(str).str.strip() != "",
    inv_key["Key_inv_vsaaa"],
    inv_key["Saskaitos_NR_norm"]
)
inv_key["Key_inv_digits"] = inv_key["Key_inv_best"].apply(only_digits)
inv_key = inv_key.rename(columns={"Klientas": "Klientas_inv", "SutartiesID": "SutartiesID_inv"})

# Vienas įrašas per raktą (fan-out fix). Jei turi datą, imame vėliausią.
inv_key = inv_key.sort_values(["Data", "Saskaitos_NR"])
inv_key = inv_key[inv_key["Key_inv_best"].astype(str).str.strip() != ""].copy()
inv_key_unique = (
    inv_key
    .drop_duplicates(subset=["Key_inv_best"], keep="last")
    [["Key_inv_best", "Key_inv_digits", "Klientas_inv", "SutartiesID_inv"]]
)

# =================== CRN susiejimas (iš Pastabų) ===================
if crn is not None:
    crn_work = crn.copy()

    # Kreditinėms raktą VISADA imame iš Pastabų (paskutinė VS/AAA/ALNUM/digits pagal aukščiau aprašytą logiką)
    if "Pastabos" in crn_work.columns:
        crn_work["Key_crn"] = crn_work["Pastabos"].apply(extract_last_invoice_ref)
    else:
        crn_work["Key_crn"] = ""  # jei nėra Pastabų – tuščia

    crn_work["Key_crn_digits"] = crn_work["Key_crn"].apply(only_digits)

    # Apsauga: KREDITINĖMS niekada nenaudojam jų SutartiesID
    crn_work["SutartiesID"] = ""

    # 1) jungimas – pagal alfanumerinį raktą
    crn_work = crn_work.merge(
        inv_key_unique,
        left_on="Key_crn",
        right_on="Key_inv_best",
        how="left",
    )

    # 2) fallback jungimas – tik pagal skaitmenis (kur dar nesusieta)
    mask_unmatched = crn_work["SutartiesID_inv"].isna() | (crn_work["SutartiesID_inv"].astype(str).str.strip() == "")
    if mask_unmatched.any():
        inv_digits_map = inv_key_unique[["Key_inv_digits", "Klientas_inv", "SutartiesID_inv"]].drop_duplicates(subset=["Key_inv_digits"])
        crn_work.loc[mask_unmatched, ["Klientas_inv", "SutartiesID_inv"]] = crn_work.loc[mask_unmatched].merge(
            inv_digits_map,
            left_on="Key_crn_digits",
            right_on="Key_inv_digits",
            how="left"
        )[["Klientas_inv_y", "SutartiesID_inv_y"]].values

    # FINAL – VISADA iš IŠRAŠYTOS sąskaitos
    crn_work["Klientas_final"] = crn_work["Klientas_inv"]
    crn_work["SutartiesID_final"] = crn_work["SutartiesID_inv"].fillna("").astype(str).str.strip()

    # Datų filtras kreditinėms
    mask_crn = crn_work["Data"].dt.date.between(nuo, iki)
    crn_f = crn_work.loc[mask_crn].copy()
else:
    crn_f = None

# Greita sumų diagnostika (turėtų nebe būti 0, jei faile buvo sumos)
if crn is not None:
    st.caption(f"💳 Kreditinių įkeltų eilučių: {len(crn)} | Bendra suma (visų): {parse_eur_robust(crn['Suma_su_PVM']).sum():,.2f}")
if crn_f is not None and not crn_f.empty:
    st.caption(f"📆 Kreditinių suma pasirinktame laikotarpyje: {crn_f['Suma_su_PVM'].sum():,.2f}")

# Jei viskas tuščia – stabdom
if inv_f.empty and (crn_f is None or crn_f.empty):
    st.info("Pasirinktame laikotarpyje duomenų nėra. Praplėsk datų intervalą.")
    st.stop()

# =================== Agregacijos (SU PVM) ===================
# Išrašytų suma
inv_sum = (
    inv_f.groupby(["Klientas", "SutartiesID"], dropna=False)["Suma_su_PVM"]
    .sum()
    .rename("Israsyta")
    .reset_index()
)

# Kreditinių suma (į faktą eis su minusu). Agreguojame tik tas, kurios turi susietą SutartiesID iš invoiso.
if crn_f is not None and not crn_f.empty:
    crn_f["Suma_su_PVM"] = parse_eur_robust(crn_f["Suma_su_PVM"]).fillna(0.0)  # dar karta, jei kas prasisuko
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

# =================== Diagnostika: ką iš Pastabų paėmė ir su kuo susiejo ===================
st.divider()
st.subheader("🔎 Diagnostika (Pastabų raktai ir susiejimas)")
if crn is not None and crn_f is not None and not crn_f.empty:
    total_crn = len(crn_f)
    matched_crn = (crn_f["SutartiesID_final"].astype(str).str.strip() != "").sum()
    st.write(f"💳 Kreditinių laikotarpyje: **{total_crn}** | Susieta: **{matched_crn}** | Nesusieta: **{total_crn - matched_crn}**")

    with st.expander("Pavyzdžiai (Pastabos → Key_crn → sutartis):", expanded=False):
        cols_dbg = [c for c in ["Data", "Saskaitos_NR", "Klientas", "Pastabos", "Key_crn", "Key_crn_digits", "SutartiesID_final", "Suma_su_PVM"] if c in crn_f.columns]
        st.dataframe(crn_f[cols_dbg].head(30), use_container_width=True)

    missing_map = crn_f[
        (crn_f["SutartiesID_final"].astype(str).str.strip() == "") |
        (crn_f["Key_crn"].astype(str).str.strip() == "")
    ].copy()
    with st.expander("Nesusietos kreditinės (neįtrauktos į sumas):", expanded=False):
        if missing_map.empty:
            st.success("Visos kreditinės susietos su išrašytomis sąskaitomis.")
        else:
            cols_diag = [
                "Data", "Saskaitos_NR", "Klientas", "Pastabos",
                "Key_crn", "Key_crn_digits", "Suma_su_PVM"
            ]
            show_diag = [c for c in cols_diag if c in missing_map.columns]
            st.dataframe(missing_map[show_diag].sort_values("Data"), use_container_width=True)
            st.info("Pastabose visada imamas paskutinis numeris (VS/AAA/ALNUM ar vien skaitmenys). Jeigu dar nesusieja – atsiųsk 2–3 eilutes diagnostikai.")

# =================== Eksportas ===================
buf = BytesIO()
with pd.ExcelWriter(buf, engine="openpyxl") as xw:
    out.to_excel(xw, sheet_name="Sutarciu_likuciai_SU_PVM", index=False)
    inv_f.to_excel(xw, sheet_name="Saskaitos_ISRASYTA_SU_PVM", index=False)
    if crn_f is not None and not crn_f.empty:
        crn_f.to_excel(xw, sheet_name="Kreditines_SU_PVM", index=False)
        missing_map = crn_f[
            (crn_f["SutartiesID_final"].astype(str).str.strip() == "") |
            (crn_f["Key_crn"].astype(str).str.strip() == "")
        ].copy()
        if not missing_map.empty:
            missing_map.to_excel(xw, sheet_name="CRN_neuzrisa", index=False)

st.download_button(
    "⬇️ Eksportuoti suvestinę (.xlsx)",
    data=buf.getvalue(),
    file_name=f"sutarciu_likuciai_SU_PVM__{nuo}_{iki}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)
