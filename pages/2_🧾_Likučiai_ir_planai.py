import streamlit as st
import pandas as pd
import numpy as np
from io import BytesIO
from decimal import Decimal, ROUND_DOWN
from datetime import date
import re

# =================== Puslapio nustatymas ===================
st.set_page_config(layout="wide")
st.markdown("## 🧾 Išrašytos ir kreditinės sąskaitos (SU PVM) – planai ir likučiai")

# Kompaktesnis išdėstymas
st.markdown("""
<style>
section.main > div { padding-top: 0rem; }
.block-container { padding-top: 0.5rem; padding-bottom: 0.75rem; }
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

# 6-ta kolona (F) – kaip atsarginis variantas
def amount_from_F(df: pd.DataFrame) -> pd.Series:
    if df is None or df.empty:
        return pd.Series([], dtype=float)
    if df.shape[1] >= 6:
        return parse_eur_robust(df.iloc[:, 5]).fillna(0.0)
    return pd.Series([0.0] * len(df), index=df.index, dtype=float)

# ---------- Normalizuotos antraštės (nekeičiant df.columns) ----------
def normalize_headers(df: pd.DataFrame):
    cols_orig = list(df.columns)
    cols_norm = [str(c).strip().upper() for c in cols_orig]
    return cols_orig, cols_norm

# --- EUR stulpelio aptikimas pagal PAVADINIMĄ (header) su normalizacija ---
def detect_currency_col_idx_headers(df: pd.DataFrame, currency: str = "EUR"):
    _, cols_norm = normalize_headers(df)
    try:
        eur_idx = cols_norm.index(currency.upper().strip())
        return eur_idx
    except ValueError:
        return None

# --- EUR stulpelio aptikimas pagal TURINĮ (langelių reikšmes) – case-insensitive ---
def detect_currency_col_idx_content(df: pd.DataFrame, currency: str = "EUR"):
    best_idx, best_count = None, -1
    target = currency.upper().strip()
    for i, c in enumerate(df.columns):
        col = df[c].astype(str).str.strip().str.upper()
        cnt = (col == target).sum()
        if cnt > best_count:
            best_idx, best_count = i, cnt
    return best_idx if best_count > 0 else None

# --- Tavo logika (robustiška): SUMOS = stulpelis prieš 'EUR' (header-based) ---
def credit_amounts_by_header_logic(df: pd.DataFrame) -> pd.Series:
    if df is None or df.empty:
        return pd.Series([], dtype=float)

    _, cols_norm = normalize_headers(df)
    amount_idx = None

    eur_idx = detect_currency_col_idx_headers(df, "EUR")
    if eur_idx is not None and eur_idx - 1 >= 0:
        amount_idx = eur_idx - 1

    if amount_idx is None:
        for i in range(len(cols_norm) - 1):
            if cols_norm[i + 1] == "EUR":
                trial = parse_eur_robust(df.iloc[:, i]).fillna(0.0)
                if trial.abs().sum() > 0:
                    amount_idx = i
                    break

    if amount_idx is None:
        return pd.Series(0.0, index=df.index, dtype=float)
    return parse_eur_robust(df.iloc[:, amount_idx]).fillna(0.0)

# --- „Universalus“ sumų nustatymas kreditinėms ---
def compute_credit_amounts(df: pd.DataFrame) -> pd.Series:
    """
    Prioritetų seka:
      (A) Jei jau yra pavadinti stulpeliai – 'Suma_su_PVM' arba 'Suma' arba 'SUM SU PVM' arba 'SUM'
      (B) 'EUR' kaip antraštė -> imam stulpelį prieš jį (case-insensitive)
      (C) 'EUR' kaip TURINYS -> imam stulpelį prieš jį (case-insensitive)
      (D) 6-ta kolona (F)
      (E) Heuristika: parenkam „labiausiai į sumas panašų“ skaitinį stulpelį
      (F) Jei nieko – nulis
    """
    if df is None or df.empty:
        return pd.Series([], dtype=float)

    # (A)
    for col in ["Suma_su_PVM", "Suma", "SUM SU PVM", "SUM"]:
        if col in df.columns:
            s = parse_eur_robust(df[col]).fillna(0.0)
            if s.abs().sum() > 0:
                return s

    # (B)
    s = credit_amounts_by_header_logic(df)
    if s.abs().sum() > 0:
        return s

    # (C)
    eur_idx = detect_currency_col_idx_content(df, "EUR")
    if eur_idx is not None and eur_idx - 1 >= 0:
        s = parse_eur_robust(df.iloc[:, eur_idx - 1]).fillna(0.0)
        if s.abs().sum() > 0:
            return s

    # (D)
    s = amount_from_F(df)
    if s.abs().sum() > 0:
        return s

    # (E)
    best_series = None
    best_score = (-1, -1.0)
    skip = {"DATA", "PASTABOS", "KLIENTAS", "SASKAITOS_NR", "TIPAS"}
    _, cols_norm = normalize_headers(df)
    for i, c in enumerate(df.columns):
        if cols_norm[i] in skip:
            continue
        ser = parse_eur_robust(df[c]).fillna(np.nan)
        nn = ser.notna().sum()
        if nn == 0:
            continue
        med = float(np.nanmedian(np.abs(ser.values)))
        if not (0.01 <= med <= 10_000_000):
            continue
        score = (nn, med)
        if score > best_score:
            best_score = score
            best_series = ser

    if best_series is not None:
        return best_series.fillna(0.0)

    # (F)
    return pd.Series(0.0, index=df.index, dtype=float)

# Raktų normalizavimas
def norm_alnum(x: str) -> str:
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
      3) kita alfanumerinė su bent 1 skaitmeniu.
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

# Kreditinių prefiksas (atsarginis filtras, jei nėra „Tipas“)
CREDIT_PREFIXES = ("COP", "KRE", "AAA")
CREDIT_RE = re.compile(r'^(?:' + '|'.join(CREDIT_PREFIXES) + r')[\s\-]*', re.IGNORECASE)
def is_credit_number(x: str) -> bool:
    return isinstance(x, str) and bool(CREDIT_RE.match(x.strip()))

# =================== Įkelti duomenys ===================
inv = ensure_df(st.session_state.get("inv_norm"))
crn_raw = ensure_df(st.session_state.get("crn_norm"))

if inv is None:
    st.warning("Įkelk **išrašytas sąskaitas** (sesijos raktas `inv_norm`) skiltyje **📥 Įkėlimas**.")
    st.stop()

# Bendra sanitarija
for df in [inv, crn_raw] if crn_raw is not None else [inv]:
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

# Išrašytų sumos (SU PVM)
inv["Suma_su_PVM"] = parse_eur_robust(inv.get("Suma_su_PVM", inv.get("Suma", 0))).fillna(0.0)

# Kreditinių pasiruošimas (sumos ir filtrai)
if crn_raw is not None:
    crn = crn_raw.copy()
    if "Tipas" in crn.columns:
        mask_credit = crn["Tipas"].astype(str).str.lower().str.contains("kredit")
        crn = crn.loc[mask_credit].copy()
    else:
        if "Saskaitos_NR" in crn.columns:
            crn = crn.loc[crn["Saskaitos_NR"].astype(str).apply(is_credit_number)].copy()
    crn["Suma_su_PVM"] = compute_credit_amounts(crn).astype(float).fillna(0.0)
    crn["SutartiesID"] = ""
else:
    crn = None

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

# =================== Išrašytos sąskaitos ===================
st.divider()
st.subheader("📄 Išrašytos sąskaitos (SU PVM)")

inv_sum = (
    inv_f.groupby(["Klientas", "SutartiesID"], dropna=False)["Suma_su_PVM"]
    .sum()
    .rename("Israsyta")
    .reset_index()
)

# REDAGUOJAMI PLANAI
if "plans" not in st.session_state:
    st.session_state["plans"] = pd.DataFrame(columns=["Klientas", "SutartiesID", "SutartiesPlanas"])

base = inv_sum[["Klientas", "SutartiesID"]].drop_duplicates().copy()
plans_old = st.session_state["plans"][["Klientas", "SutartiesID", "SutartiesPlanas"]] if not st.session_state["plans"].empty else None
if plans_old is not None and not plans_old.empty:
    plans = pd.merge(base, plans_old, how="left", on=["Klientas", "SutartiesID"])
else:
    plans = base.copy()
    plans["SutartiesPlanas"] = 0.0

plans["SutartiesPlanas"] = pd.to_numeric(plans["SutartiesPlanas"], errors="coerce").fillna(0.0)

st.markdown("### ✍️ Įvesk sutarčių planus (SU PVM)")
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
        "SutartiesPlanas": st.column_config.NumberColumn("Sutarties suma (planas) €", step=0.01, format="%.2f"),
    },
)
plans["Klientas"] = plans["Klientas"].astype(str).str.strip()
plans["SutartiesID"] = plans["SutartiesID"].astype(str).str.strip()
st.session_state["plans"] = plans

# =================== Kreditinių sąrašas (be susiejimo) ===================
st.divider()
st.subheader("💳 Kreditinės (SU PVM) – be susiejimo")

if crn_f is None or crn_f.empty:
    st.info("Pasirinktame laikotarpyje **kreditinių nėra**.")
    total_kred = 0.0
    cols_crn = []
else:
    crn_f["Suma_su_PVM"] = crn_f["Suma_su_PVM"].astype(float).fillna(0.0).apply(floor2)
    total_kred = float(crn_f["Suma_su_PVM"].sum())
    cols_crn = [c for c in ["Data", "Saskaitos_NR", "Klientas", "Pastabos", "Suma_su_PVM", "Tipas"] if c in crn_f.columns]
    st.dataframe(
        crn_f[cols_crn].sort_values(["Data","Saskaitos_NR"]) if "Data" in cols_crn else crn_f[cols_crn],
        use_container_width=True
    )

c1, c2 = st.columns(2)
c1.metric("Kreditinių kiekis", "0" if crn_f is None else f"{len(crn_f)}")
c2.metric("Kreditinių suma (SU PVM)", f"{total_kred:,.2f} €")

# =================== Likutis pagal sutartį (automatinis pririšimas per išrašytą sąskaitą) ===================
st.divider()
st.subheader("🔗 Kreditinių pririšimas prie sutarčių (per išrašytos sąskaitos numerį)")

# 1) Raktas iš IŠRAŠYTŲ sąskaitų numerio (VS..., AAA..., arba pats numeris)
inv_key = (
    inv[["Data", "Saskaitos_NR", "Klientas", "SutartiesID"]]
    .dropna(subset=["Saskaitos_NR"])
    .copy()
)

def extract_from_number(nr: str) -> str:
    if pd.isna(nr): return ""
    s = str(nr).upper()
    m = re.search(r'(VS[^\s]+)$', s) or re.search(r'(AAA[^\s]+)$', s)
    return norm_alnum(m.group(1)) if m else norm_alnum(s)

inv_key["Key_inv_best"] = inv_key["Saskaitos_NR"].apply(extract_from_number)
inv_key = inv_key.rename(columns={"Klientas": "Klientas_inv", "SutartiesID": "SutartiesID_inv"})
inv_key = inv_key.sort_values(["Data", "Saskaitos_NR"])
inv_key = inv_key[inv_key["Key_inv_best"].astype(str).str.strip() != ""].copy()
inv_key_unique = (
    inv_key.drop_duplicates(subset=["Key_inv_best"], keep="last")
           [["Key_inv_best", "Klientas_inv", "SutartiesID_inv"]]
)

# 2) Iš KREDITINIŲ: nuoroda į išrašytą sąskaitą iš „Pastabų“
if crn_f is None or crn_f.empty:
    st.info("Kreditinių šiame laikotarpyje nėra – pririšti nėra ko.")
    out = pd.merge(plans, inv_sum, how="left", on=["Klientas", "SutartiesID"]).fillna({"Israsyta": 0.0})
    out["Israsyta"] = out["Israsyta"].apply(floor2)
    out["Kredituota"] = 0.0
    out["Faktas"] = out["Israsyta"]
    out["Like"] = (out["SutartiesPlanas"] - out["Faktas"]).apply(floor2)
else:
    work = crn_f.copy()
    work["Key_ref"] = work.get("Pastabos", pd.Series(index=work.index, dtype=str)).apply(extract_last_from_notes)

    # 3) Sujungiame kreditinę su IŠRAŠYTA sąskaita per nuorodos raktą
    work = work.merge(inv_key_unique, left_on="Key_ref", right_on="Key_inv_best", how="left")

    # 4) Kreditinės sumos (teigiama reikšmė mažinimui)
    work["Suma_su_PVM"] = work["Suma_su_PVM"].astype(float).fillna(0.0)
    work["Kredituota_pos"] = work["Suma_su_PVM"].abs()

    # 5) Paliekame tik tas kreditines, kurios sėkmingai paveldėjo sutartį iš IŠRAŠYTOS sąskaitos
    work_ok = work[work["SutartiesID_inv"].astype(str).str.strip() != ""].copy()

    # 6) Agreguojame „Kredituota“ sutarties lygiu
    if not work_ok.empty:
        crn_sum = (
            work_ok.groupby(["Klientas_inv", "SutartiesID_inv"], dropna=False)["Kredituota_pos"]
            .sum()
            .reset_index()
            .rename(columns={
                "Klientas_inv": "Klientas",
                "SutartiesID_inv": "SutartiesID",
                "Kredituota_pos": "Kredituota"
            })
        )
    else:
        crn_sum = pd.DataFrame(columns=["Klientas", "SutartiesID", "Kredituota"])

    # 7) Į Likučius: sujungiame „Kredituota“ ir perskaičiuojame Faktą/Like
    out = pd.merge(plans, inv_sum, how="left", on=["Klientas", "SutartiesID"]).fillna({"Israsyta": 0.0})
    out = pd.merge(out, crn_sum, how="left", on=["Klientas", "SutartiesID"]).fillna({"Kredituota": 0.0})
    out["Israsyta"]  = out["Israsyta"].apply(floor2)
    out["Kredituota"] = out["Kredituota"].apply(floor2)
    out["Faktas"]    = (out["Israsyta"] - out["Kredituota"]).apply(floor2)
    out["Like"]      = (out["SutartiesPlanas"] - out["Faktas"]).apply(floor2)

    # 8) Metrika – kiek kreditinių pavyko pririšti
    st.metric("Pririštų kreditinių skaičius", f"{len(work_ok):,}")

# =================== KPI ir Likučių lentelė ===================
st.divider()
st.subheader("📊 Sutarčių likučiai (SU PVM)")

out = out.fillna(0.0)
total_planas = floor2(out["SutartiesPlanas"].sum())
total_israsyta = floor2(out["Israsyta"].sum())
total_kred = floor2(out.get("Kredituota", pd.Series(0.0, index=out.index)).sum())
total_faktas = floor2(out["Faktas"].sum())
total_like = floor2(total_planas - total_faktas)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Išrašyta € (SU PVM)", f"{total_israsyta:,.2f}")
c2.metric("Kredituota € (SU PVM)", f"{total_kred:,.2f}")
c3.metric("Faktas € (SU PVM)", f"{total_faktas:,.2f}")
c4.metric("Likutis € (SU PVM)", f"{total_like:,.2f}")

def progress_bar(p: float) -> str:
    p = 0.0 if pd.isna(p) else float(p)
    p = max(0.0, p)
    blocks = int(min(100.0, p) // 5)
    return "█" * blocks + "░" * (20 - blocks) + f"  {p:.1f}%"

den = out["SutartiesPlanas"].replace(0, np.nan)
out["PctIsnaudota"] = np.where(den.isna(), 0.0, (out["Faktas"] / den) * 100.0)
out["PctIsnaudota"] = out["PctIsnaudota"].clip(lower=0, upper=999)
out["Progresas"] = out["PctIsnaudota"].apply(progress_bar)

cols_order = [
    "Klientas", "SutartiesID", "SutartiesPlanas",
    "Israsyta", "Kredituota", "Faktas", "Like",
    "PctIsnaudota", "Progresas"
]
show_cols = [c for c in cols_order if c in out.columns]
st.dataframe(out[show_cols].sort_values(["Klientas", "SutartiesID"]), use_container_width=True)

# =================== Konkrečios sutarties išklotinė + eksportai ===================
st.divider()
st.subheader("🎯 Konkrečios sutarties išklotinė")

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
        kred = floor2(one.get("Kredituota", pd.Series([0.0])).sum())
        faktas = floor2(one["Faktas"].sum())
        likutis = floor2(planas - faktas)

        c1, c2, c3 = st.columns(3)
        c1.metric("Išrašyta €", f"{israsyta:,.2f}")
        c2.metric("Kredituota €", f"{kred:,.2f}")
        c3.metric("Faktas €", f"{faktas:,.2f}")

        c4, c5, c6 = st.columns(3)
        c4.metric("Planas €", f"{planas:,.2f}")
        c5.metric("Likutis €", f"{likutis:,.2f}")
        c6.metric("% išnaudota", f"{0.0 if planas == 0 else floor2((faktas / planas) * 100):,.2f}%")

        st.dataframe(one[show_cols], use_container_width=True)

        # Eksportas – tik ši sutartis
        buf_one = BytesIO()
        with pd.ExcelWriter(buf_one, engine="openpyxl") as xw:
            one[show_cols].to_excel(xw, sheet_name=safe_sheet_name(sel_contract, "Sutartis"), index=False)
        st.download_button(
            "⬇️ Atsisiųsti šios sutarties išklotinę (.xlsx)",
            data=buf_one.getvalue(),
            file_name=f"{safe_filename(sel_client)}__{safe_filename(sel_contract)}__{nuo}_{iki}__likutis_SU_PVM.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
else:
    st.info("Pasirink **Klientą** ir **Sutartį**.")

# Bendras eksportas – visa suvestinė
buf_all = BytesIO()
with pd.ExcelWriter(buf_all, engine="openpyxl") as xw:
    out[show_cols].to_excel(xw, sheet_name="Sutarciu_likuciai_SU_PVM", index=False)
    inv_f.to_excel(xw, sheet_name="Saskaitos_ISRASYTA_SU_PVM", index=False)
    if crn_f is not None and not crn_f.empty:
        cols_crn = [c for c in ["Data","Saskaitos_NR","Klientas","Pastabos","Suma_su_PVM","Tipas"] if c in crn_f.columns]
        crn_f[cols_crn].to_excel(xw, sheet_name="Kreditines_SU_PVM", index=False)

st.download_button(
    "⬇️ Eksportuoti suvestinę (.xlsx)",
    data=buf_all.getvalue(),
    file_name=f"sutarciu_likuciai_SU_PVM__{nuo}_{iki}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)
