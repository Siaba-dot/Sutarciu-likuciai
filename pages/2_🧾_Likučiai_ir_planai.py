import streamlit as st

import pandas as pd
import numpy as np
from io import BytesIO
from decimal import Decimal, ROUND_DOWN
from datetime import date
import re

# Rekomenduojama: platus išdėstymas
st.set_page_config(layout="wide")
st.markdown("## 🧾 Likučiai ir planai (sumos SU PVM)")

# ========= Pagalbinės =========
def floor2(x):
    """Nukerpa iki 2 skaičių po kablelio (be apvalinimo)."""
    try:
        return float(Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_DOWN))
    except Exception:
        return 0.0

def ensure_df(src):
    """Tikimės DataFrame iš Įkėlimo puslapio."""
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
    """Saugus Excel lapo pavadinimas – be : \ / ? * [ ] ir ≤ 31 simbolio."""
    name = "" if name is None else str(name)
    name = re.sub(r'[:\\/*?\[\]]', "_", name).strip()
    if not name:
        name = fallback
    return name[:31]

def safe_filename(name: str, max_len: int = 150) -> str:
    """Saugus failo vardas daugumai OS/naršyklių."""
    name = "" if name is None else str(name)
    name = re.sub(r'[\\/:*?"<>|\r\n]+', "_", name).strip(" .")
    return (name or "export")[:max_len]

# ========= Kreditinių numerių atpažinimas =========
# Pagal tavo taisyklę kreditinės gali prasidėti COP / KRE / AAA
CREDIT_PREFIXES = ("COP", "KRE", "AAA")
CREDIT_RE = re.compile(r'^(?:' + '|'.join(CREDIT_PREFIXES) + r')[\s\-]*', re.IGNORECASE)

def is_credit_number(x: str) -> bool:
    """Ar tekstas atrodo kaip kreditinės numeris pagal suderintus prefiksus?"""
    return isinstance(x, str) and bool(CREDIT_RE.match(x.strip()))

# ========= Kreditinių normalizatorius (fallback, jei crn_norm ateina „žalias“) =========
def normalize_credit_df_if_needed(crn_raw: pd.DataFrame | None) -> pd.DataFrame | None:
    """
    Jei kreditinės atėjo kaip „be antraščių“ failas (A=Data, B=Kreditinės_NR, D=Klientas, E=Pastabos, F=Suma_su_PVM),
    normalizuojam iki bendros schemos: Data, Saskaitos_NR (kreditinės), Klientas, Pastabos, Suma_su_PVM, Susieta_Inv_NR, Tipas.
    """
    if crn_raw is None or crn_raw.empty:
        return crn_raw

    cols = [c.lower() for c in crn_raw.columns.astype(str).tolist()]
    # Jei panašu, kad jau normalizuota (turi bent Data ir Saskaitos_NR), paliekam kaip yra
    if set(["data", "saskaitos_nr"]).issubset(set(cols)):
        d = crn_raw.copy()
        d["Data"] = pd.to_datetime(d["Data"], errors="coerce")
        d["Suma_su_PVM"] = pd.to_numeric(d.get("Suma_su_PVM", 0), errors="coerce").fillna(0.0)
        if "Tipas" not in d.columns:
            d["Tipas"] = "Kreditinė"
        if "Susieta_Inv_NR" not in d.columns:
            inv_regex = re.compile(r"(VS\s*[-–]?\s*\d{4,7})", re.IGNORECASE)
            d["Susieta_Inv_NR"] = (
                d.get("Pastabos", pd.Series(index=d.index, dtype=str)).astype(str)
                 .str.extract(inv_regex, expand=False)
                 .str.replace(" ", "", regex=False)
                 .str.upper()
            )
        return d

    # Interpretuojam kaip A,B,D,E,F (be antraščių)
    try:
        df = crn_raw.copy()
        pick = [0, 1, 3, 4, 5]  # A,B,D,E,F
        if df.shape[1] >= 6:
            df = df.iloc[:, pick]
        df.columns = ["Data", "Kreditines_NR", "Klientas", "Pastabos", "Suma_su_PVM"]

        df["Data"] = pd.to_datetime(df["Data"], errors="coerce")
        df["Suma_su_PVM"] = pd.to_numeric(df["Suma_su_PVM"], errors="coerce")
        df = df.dropna(how="all")

        # Tikros kreditinės pagal prefiksus
        mask_crn = df["Kreditines_NR"].astype(str).apply(is_credit_number)
        df = df.loc[mask_crn].copy()

        # Iš Pastabų iškeliame susietą VS- numerį (jei keli – imam paskutinį)
        INV_RE_ALL = re.compile(r"(VS\s*[-–]?\s*\d{4,7})", re.IGNORECASE)
        def extract_last_vs(s):
            if pd.isna(s):
                return pd.NA
            hits = INV_RE_ALL.findall(str(s))
            if not hits:
                return pd.NA
            return hits[-1].replace(" ", "").upper()

        df["Susieta_Inv_NR"] = df["Pastabos"].apply(extract_last_vs)

        df = df.rename(columns={"Kreditines_NR": "Saskaitos_NR"})
        df["Saskaitos_NR"] = df["Saskaitos_NR"].astype(str).str.strip().str.upper()
        df["Klientas"] = df["Klientas"].astype(str).str.strip()
        df["Tipas"] = "Kreditinė"
        return df.dropna(subset=["Data"]).reset_index(drop=True)
    except Exception:
        # Nepavyko – grąžinam originalą
        return crn_raw

# ========= Duomenys iš sesijos =========
inv = ensure_df(st.session_state.get("inv_norm"))
crn = ensure_df(st.session_state.get("crn_norm"))

if inv is None:
    st.warning("Įkelk duomenis skiltyje **📥 Įkėlimas**.")
    st.stop()

# ---- Tipų sanitarija
for df in [inv, crn] if crn is not None else [inv]:
    df["Data"] = pd.to_datetime(df["Data"], errors="coerce")
    if "Klientas" in df.columns:
        df["Klientas"] = df["Klientas"].astype(str).str.strip()
    if "SutartiesID" not in df.columns:
        df["SutartiesID"] = ""
    else:
        df["SutartiesID"] = df["SutartiesID"].astype(str).str.strip()
    df["Suma_su_PVM"] = pd.to_numeric(df.get("Suma_su_PVM", df.get("Suma", 0)), errors="coerce").fillna(0.0)
    if "Saskaitos_NR" in df.columns:
        df["Saskaitos_NR"] = df["Saskaitos_NR"].astype(str).str.strip().str.upper()

# ---- Jei kreditinės dar „žalios“, normalizuojam
if crn is not None:
    crn = normalize_credit_df_if_needed(crn)

# ========= 📅 Laikotarpio filtras =========
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

# Filtrai
mask_inv = inv["Data"].dt.date.between(nuo, iki)
inv_f = inv.loc[mask_inv].copy()

# Paruošiam „raktą“ susiejimui: invoice NR -> klientas, sutartis (iš visų invoisų, ne tik filtro)
inv_key = (
    inv[["Saskaitos_NR", "Klientas", "SutartiesID"]]
    .dropna(subset=["Saskaitos_NR"])
    .copy()
)
inv_key["Saskaitos_NR"] = inv_key["Saskaitos_NR"].astype(str).str.strip().str.upper()

if crn is not None:
    crn_work = crn.copy()

    # Tikros kreditinės pagal prefiksus
    if "Saskaitos_NR" in crn_work.columns:
        crn_work = crn_work[crn_work["Saskaitos_NR"].astype(str).apply(is_credit_number)].copy()

    # Jei trūksta Susieta_Inv_NR – ištraukiam (paskutinį VS-… iš Pastabų)
    if "Susieta_Inv_NR" not in crn_work.columns:
        INV_RE_ALL = re.compile(r"(VS\s*[-–]?\s*\d{4,7})", re.IGNORECASE)
        crn_work["Susieta_Inv_NR"] = (
            crn_work.get("Pastabos", pd.Series(index=crn_work.index, dtype=str)).astype(str)
            .apply(lambda s: (lambda hits: hits[-1] if hits else pd.NA)(INV_RE_ALL.findall(s)))
            .str.replace(" ", "", regex=False)
            .str.upper()
        )

    # Susiejimas prie invoiso
    crn_work["Susieta_Inv_NR"] = crn_work["Susieta_Inv_NR"].astype(str).str.strip().str.upper()
    crn_work = crn_work.merge(
        inv_key,
        left_on="Susieta_Inv_NR",
        right_on="Saskaitos_NR",
        how="left",
        suffixes=("", "_inv"),
    )

    # Užpildom trūkstamą klientą/sutartį iš invoiso
    crn_work["Klientas"] = np.where(
        crn_work["Klientas"].astype(str).str.strip().eq(""),
        crn_work["Klientas_inv"],
        crn_work["Klientas"],
    )
    crn_work["SutartiesID"] = np.where(
        crn_work["SutartiesID"].astype(str).str.strip().eq(""),
        crn_work["SutartiesID_inv"].astype(str),
        crn_work["SutartiesID"].astype(str),
    )

    # Datų filtras
    mask_crn = crn_work["Data"].dt.date.between(nuo, iki)
    crn_f = crn_work.loc[mask_crn].copy()
else:
    crn_f = None

if inv_f.empty and (crn_f is None or crn_f.empty):
    st.info("Pasirinktame laikotarpį duomenų nėra. Praplėsk datų intervalą.")
    st.stop()

# ========= Agregacijos (SU PVM) =========
# Invoisų suma – teigiama
inv_sum = (
    inv_f.groupby(["Klientas", "SutartiesID"], dropna=False)["Suma_su_PVM"]
    .sum()
    .rename("Israsyta")
    .reset_index()
)

# Kreditinių suma – rodoma teigiama, bet į Faktą eis su minusu
if crn_f is not None and not crn_f.empty:
    crn_f["Kredituota_signed"] = -crn_f["Suma_su_PVM"].abs()
    crn_sum_signed = (
        crn_f.groupby(["Klientas", "SutartiesID"], dropna=False)["Kredituota_signed"]
        .sum()
        .reset_index()
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

# Faktas = Išrašyta + (neigiamas kreditas) -> t.y. IŠRAŠYTA - KREDITUOTA
fact["Faktas"] = fact["Israsyta"] + fact["Kredituota_signed"]

# ========= REDAGUOJAMI PLANAI =========
# Išsaugome naudotojo įvestus planus tarp perėjimų ir laikotarpių
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
st.session_state["plans"] = plans  # išsaugom

# ========= Likučiai =========
out = pd.merge(plans, fact, how="left", on=["Klientas", "SutartiesID"]).fillna(0.0)
out["Israsyta"] = out["Israsyta"].apply(floor2)
out["Kredituota"] = out["Kredituota"].apply(floor2)  # teigiama rodymo reikšmė
out["Faktas"] = out["Faktas"].apply(floor2)
out["Like"] = (out["SutartiesPlanas"] - out["Faktas"]).apply(floor2)

# ========= KPI =========
total_planas = floor2(out["SutartiesPlanas"].sum())
total_israsyta = floor2(out["Israsyta"].sum())
total_kred = floor2(out["Kredituota"].sum())              # rodoma teigiama suma
total_faktas = floor2(out["Faktas"].sum())                # jau su atimtom kreditinėm
total_like = floor2(total_planas - total_faktas)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Išrašyta € (su PVM)", f"{total_israsyta:,.2f}")
c2.metric("Kredituota € (su PVM)", f"{total_kred:,.2f}")
c3.metric("Faktas € (su PVM)", f"{total_faktas:,.2f}")
c4.metric("Likutis € (su PVM)", f"{total_like:,.2f}")

# ========= Progreso juosta =========
def progress_bar(p: float) -> str:
    p = 0.0 if pd.isna(p) else float(p)
    p = max(0.0, p)
    blocks = int(min(100.0, p) // 5)
    return "█" * blocks + "░" * (20 - blocks) + f"  {p:.1f}%"

den = out["SutartiesPlanas"].replace(0, np.nan)
out["PctIsnaudota"] = np.where(den.isna(), 0.0, (out["Faktas"] / den) * 100.0)
out["PctIsnaudota"] = out["PctIsnaudota"].clip(lower=0, upper=999)
out["Progresas"] = out["PctIsnaudota"].apply(progress_bar)

# ========= Pagrindinė lentelė =========
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

# ========= 🎯 Filtras: Klientas -> Sutartis =========
st.divider()
st.subheader("🎯 Konkrečios sutarties likutis")

sel_df = out.copy()
sel_df["Klientas"] = sel_df["Klientas"].astype(str).str.strip()
sel_df["SutartiesID"] = sel_df["SutartiesID"].astype(str).str.strip()
klientai = sorted([k for k in sel_df["Klientas"].dropna().unique().tolist() if k])
sel_client = st.selectbox("Pasirink Klientą", options=klientai, index=0 if klientai else None)

sutartys = []
if sel_client:
    sutartys = sorted(
        sel_df.loc[sel_df["Klientas"] == sel_client, "SutartiesID"]
        .dropna().astype(str).str.strip().unique().tolist()
    )
sel_contract = st.selectbox("Pasirink Sutartį", options=sutartys, index=0 if sutartys else None)

if sel_client and sel_contract:
    one = sel_df[(sel_df["Klientas"] == sel_client) & (sel_df["SutartiesID"] == sel_contract)].copy()
    if not one.empty:
        planas = floor2(one["SutartiesPlanas"].sum())
        israsyta = floor2(one["Israsyta"].sum())
        kred = floor2(one["Kredituota"].sum())
        faktas = floor2(one["Faktas"].sum())
        likutis = floor2(planas - faktas)

        c1, c2, c3 = st.columns(3)
        c1.metric("Išrašyta € (su PVM)", f"{israsyta:,.2f}")
        c2.metric("Kredituota € (su PVM)", f"{kred:,.2f}")
        c3.metric("Faktas € (su PVM)", f"{faktas:,.2f}")

        c4, c5, c6 = st.columns(3)
        c4.metric("Planas € (su PVM)", f"{planas:,.2f}")
        c5.metric("Likutis € (su PVM)", f"{likutis:,.2f}")
        c6.metric("% išnaudota", f"{0.0 if planas == 0 else floor2((faktas / planas) * 100):,.2f}%")

        st.dataframe(one[show_cols], use_container_width=True)
        # ======= Eksportas – tik ši sutartis =======
        sheet = safe_sheet_name(sel_contract, fallback="Sutartis")
        fname_client = safe_filename(sel_client)
        fname_contract = safe_filename(sel_contract)
        nuo_str, iki_str = str(nuo), str(iki)

        buf_one = BytesIO()
        with pd.ExcelWriter(buf_one, engine="openpyxl") as xw:
            one.to_excel(xw, sheet_name=sheet, index=False)

        st.download_button(
            "⬇️ Atsisiųsti šios sutarties išklotinę (.xlsx)",
            data=buf_one.getvalue(),
            file_name=f"{fname_client}__{fname_contract}__{nuo_str}_{iki_str}__likutis_SU_PVM.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
else:
    st.info("Pasirink **Klientą** ir **Sutartį**.")

# ========= Diagnostika: kreditinių susiejimas =========
if crn_f is not None and not crn_f.empty:
    missing_map = crn_f[
        crn_f["Susieta_Inv_NR"].isna() |
        (crn_f["SutartiesID"].astype(str).str.strip() == "")
    ].copy()
    with st.expander("🔎 Kreditinių susiejimo diagnostika", expanded=False):
        st.write("Nesusietos / be kontrakto kreditinės (jei yra):")
        if missing_map.empty:
            st.success("Visos kreditinės sėkmingai pririštos prie sutarties.")
        else:
            st.dataframe(
                missing_map[
                    ["Data", "Saskaitos_NR", "Klientas", "Susieta_Inv_NR", "SutartiesID", "Suma_su_PVM"]
                ].sort_values("Data"),
                use_container_width=True
            )

# ========= Eksportas – visa suvestinė (pagal laikotarpį) =========
buf = BytesIO()
with pd.ExcelWriter(buf, engine="openpyxl") as xw:
    out.to_excel(xw, sheet_name="Sutarciu_likuciai_SU_PVM", index=False)
    inv_f.to_excel(xw, sheet_name="Saskaitos_ISRASYTA_SU_PVM", index=False)
    if crn_f is not None and not crn_f.empty:
        crn_f.to_excel(xw, sheet_name="Kreditines_SU_PVM", index=False)
        # Papildomai – neužsirišusios kreditinės
        missing_map = crn_f[
            crn_f["Susieta_Inv_NR"].isna() |
            (crn_f["SutartiesID"].astype(str).str.strip() == "")
        ].copy()
        if not missing_map.empty:
            missing_map.to_excel(xw, sheet_name="CRN_neuzrisa", index=False)

st.download_button(
    "⬇️ Eksportuoti suvestinę (.xlsx)",
    data=buf.getvalue(),
    file_name=f"sutarciu_likuciai_SU_PVM__{nuo}_{iki}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)

