# pages/3_📈_MoM_WoW_kiekiai.py
import streamlit as st
import pandas as pd
import numpy as np
from datetime import date
import re
import unicodedata
import plotly.graph_objects as go
import plotly.io as pio

# ------------------------------------------------------------
# Puslapio nustatymai ir tema
# ------------------------------------------------------------
st.set_page_config(layout="wide")

st.markdown("""
<style>
  .block-container {padding-top: 0.5rem; padding-bottom: 0.75rem; max-width: 1500px;}
  header[data-testid="stHeader"] {height: 0rem; visibility: hidden;}
  h1, .stMarkdown h1 {font-size: 1.55rem; line-height: 1.2; margin: 0.2rem 0 0.6rem 0;}
  h2, .stMarkdown h2 {font-size: 1.25rem; line-height: 1.25; margin: 0.1rem 0 0.4rem 0;}
  h3, .stMarkdown h3 {font-size: 1.05rem; line-height: 1.25; margin: 0.1rem 0 0.3rem 0;}
  div[data-testid="stVerticalBlock"] > div:has(.stRadio),
  div[data-testid="stVerticalBlock"] > div:has(.stDateInput),
  div[data-testid="stVerticalBlock"] > div:has(.stToggle) {margin-top: 0.25rem; margin-bottom: 0.25rem;}
  .modebar {transform: scale(0.95); transform-origin: top right;}
</style>
""", unsafe_allow_html=True)

pio.templates["sigita_dark"] = go.layout.Template(
    layout=dict(
        template="plotly_dark",
        font=dict(family="Inter, Segoe UI, system-ui", size=13, color="#E6E6E6"),
        paper_bgcolor="#0f1116",
        plot_bgcolor="#0f1116",
        colorway=["#00E5FF", "#76A9FA", "#22D3EE", "#60A5FA"],
        hoverlabel=dict(bgcolor="#111827", font_size=13),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        xaxis=dict(gridcolor="#1f2937"),
        yaxis=dict(gridcolor="#1f2937"),
    )
)
pio.templates.default = "sigita_dark"

st.header("📈 Dokumentų kiekio dinamika (MoM & WoW)")

# ------------------------------------------------------------
# Pagalbinės
# ------------------------------------------------------------
def ensure_df(src):
    return src if isinstance(src, pd.DataFrame) else None

def _norm_colname(c: str) -> str:
    if c is None: return ""
    s = str(c).strip().lower()
    s = "".join(ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch))
    s = re.sub(r"[\s\-.]+", "_", s)
    s = re.sub(r"[^a-z0-9_]", "", s)
    return s

def find_column(df: pd.DataFrame, candidates: list[str]) -> str | None:
    if df is None or df.empty: return None
    norm_map = {_norm_colname(c): c for c in df.columns}
    for cand in candidates:
        nc = _norm_colname(cand)
        if nc in norm_map: return norm_map[nc]
    # dalinis atitikimas
    cols_norm = list(norm_map.keys())
    for cand in candidates:
        nc = _norm_colname(cand)
        hit = [norm_map[k] for k in cols_norm if nc in k]
        if hit: return hit[0]
    return None

def pick_id_column_strict(df: pd.DataFrame) -> str | None:
    """Dokumento numeris (ANTRAŠTĖS lygio). Griežtai NE 'Numeris/No/Dok_ID' (eilutės ID)."""
    prefer = [
        "Saskaitos_NR","Sąskaitos_NR","Saskaitos NR","Sąskaitos NR",
        "Saskaitos numeris","Sąskaitos numeris",
        "Dokumento_Nr","Dokumento Nr","Dokumento numeris",
        "InvoiceNo","Invoice No"
    ]
    return find_column(df, prefer)

def pick_date_column(df: pd.DataFrame) -> str | None:
    """Dokumento data (ANTRAŠTĖS lygio)."""
    prefer = [
        "Data","Dokumento_Data","Dokumento data",
        "Saskaitos_Data","Sąskaitos data",
        "Išrašymo data","Israsymo data",
        "InvoiceDate","Invoice Date","Document Date"
    ]
    return find_column(df, prefer)

def coerce_date_col(df: pd.DataFrame, col: str):
    if df is None or col is None or col not in df.columns: return df
    d = df.copy()
    d[col] = pd.to_datetime(d[col], errors="coerce", dayfirst=True)  # LT formatas
    return d

def to_period_series(s: pd.Series, granularity: str) -> pd.Series:
    return s.dt.to_period("M").astype(str) if granularity == "M" else s.dt.to_period("W-MON").astype(str)

def period_start_ts(p: str, granularity: str) -> pd.Timestamp:
    try:
        return pd.Period(p, freq=("M" if granularity == "M" else "W-MON")).start_time
    except Exception:
        return pd.NaT

def moving_average(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window=window, min_periods=1).mean()

def min_max_date(*dfs):
    frames = [d for d in dfs if d is not None and not d.empty]
    if not frames:
        today = pd.Timestamp.today().normalize()
        return today, today
    all_dates = []
    for d in frames:
        if "Data" in d.columns:
            all_dates.append(pd.to_datetime(d["Data"], errors="coerce", dayfirst=True))
    if not all_dates:
        today = pd.Timestamp.today().normalize()
        return today, today
    s = pd.concat(all_dates, axis=0).dropna()
    if s.empty:
        today = pd.Timestamp.today().normalize()
        return today, today
    return s.min().normalize(), s.max().normalize()

def build_doc_level(df_raw: pd.DataFrame, id_col: str, date_col: str) -> pd.DataFrame:
    """
    Iš VISŲ eilučių (nepo filtro) sukonstruoja dokumentų lygį:
      1 eil. = 1 dokumentas; Data = min(data) per dokumentą (antraštės data).
    """
    if df_raw is None or df_raw.empty or id_col is None or date_col is None:
        return pd.DataFrame(columns=["Data", id_col])
    d = df_raw[[id_col, date_col]].copy()
    d[date_col] = pd.to_datetime(d[date_col], errors="coerce", dayfirst=True)
    d = d.dropna(subset=[id_col, date_col])
    out = (
        d.groupby(id_col, as_index=False)[date_col]
         .min()
         .rename(columns={date_col: "Data"})
    )
    return out

def counts_unique_docs(doc_df: pd.DataFrame, id_col: str, granularity: str) -> pd.DataFrame:
    """Dokumentų lygis -> kiekis per periodą (unikalūs)."""
    if doc_df is None or doc_df.empty:
        return pd.DataFrame(columns=["Periodas", "Kiekis"])
    d = doc_df.copy()
    d["Data"] = pd.to_datetime(d["Data"], errors="coerce", dayfirst=True)
    d = d.dropna(subset=["Data", id_col])
    d["Periodas"] = to_period_series(d["Data"], "M" if granularity == "M" else "W")
    d = d.drop_duplicates(subset=["Periodas", id_col])  # vienas doc per periodą 1 kartą
    return (
        d.groupby("Periodas")[id_col]
         .size()
         .reset_index(name="Kiekis")
         .sort_values("Periodas")
         .reset_index(drop=True)
    )

# --- Kritinis: kreditinių prefiksų filtras (dokumentų numeriui) ---
CREDIT_PREFIX_RE = r'^\s*(?:COP|KRE|AAA)(?:[\s\-]?)'  # leidžiam tarpą/brūkšnį po prefikso

def filter_credit_by_prefix(df: pd.DataFrame, id_col: str) -> pd.DataFrame:
    if df is None or df.empty or id_col is None or id_col not in df.columns:
        return pd.DataFrame(columns=df.columns if df is not None else [])
    s = df[id_col].astype(str).str.upper().str.strip()
    mask = s.str.match(CREDIT_PREFIX_RE, na=False)
    return df.loc[mask].copy()

# ------------------------------------------------------------
# Duomenys iš sesijos
# ------------------------------------------------------------
inv_raw = ensure_df(st.session_state.get("inv_norm"))
crn_raw = ensure_df(st.session_state.get("crn_norm"))

if inv_raw is None:
    st.warning("Įkelk duomenis skiltyje **📥 Įkėlimas**.")
    st.stop()

# ID ir DATA stulpeliai (griežtai)
inv_id = pick_id_column_strict(inv_raw)
inv_date_col = pick_date_column(inv_raw)
if inv_id is None or inv_date_col is None:
    with st.expander("Diagnostika: INV ID/DATA"):
        st.write("inv_raw stulpeliai:", list(inv_raw.columns))
    st.error("INV privalo turėti dokumento numerį ir datą (antraštės lygio).")
    st.stop()

crn_id = pick_id_column_strict(crn_raw) if crn_raw is not None else None
crn_date_col = pick_date_column(crn_raw) if crn_raw is not None else None

# Datų parse (dayfirst) – nekeičiam ID
inv_raw = coerce_date_col(inv_raw, inv_date_col)
if crn_raw is not None and crn_date_col:
    crn_raw = coerce_date_col(crn_raw, crn_date_col)

# ------------------------------------------------------------
# UI: periodiškumas / slankus / laikotarpis
# ------------------------------------------------------------
st.subheader("Periodiškumas")
gran_label = st.radio(" ", options=["Mėnuo (MoM)", "Savaitė (WoW)"], horizontal=True, index=0)
gran = "M" if "Mėnuo" in gran_label else "W"

c1, c2 = st.columns(2)
with c1:
    show_ma = st.toggle("Rodyti slankų vidurkį (3 mėn. / 4 sav.)", value=True)
with c2:
    crn_negative = st.toggle("Kreditines skaičiuoti su minusu", value=False)

# Laikotarpis – iš visų datų, su dayfirst
dmin, dmax = min_max_date(
    inv_raw.rename(columns={inv_date_col: "Data"}),
    None if crn_raw is None or crn_date_col is None else crn_raw.rename(columns={crn_date_col: "Data"})
)
rng = st.date_input(
    "Laikotarpis (nuo – iki)",
    value=(dmin.date(), dmax.date()),
    min_value=dmin.date(),
    max_value=max(dmax.date(), dmin.date()),
    format="YYYY-MM-DD"
)
if isinstance(rng, (tuple, list)) and len(rng) == 2:
    nuo, iki = rng
elif isinstance(rng, date):
    nuo, iki = rng, rng
else:
    nuo, iki = dmin.date(), dmax.date()

# ------------------------------------------------------------
# *** Kritiška: CRN filtras pagal prefiksą COP|KRE|AAA ***
# ------------------------------------------------------------
if crn_raw is not None and crn_id:
    crn_raw = filter_credit_by_prefix(crn_raw, crn_id)
    # Jei po filtro tuščia – nėra kreditinių
    if crn_raw.empty:
        crn_raw = None

# ------------------------------------------------------------
# Dokumentų LYGIO lentelės (iš VISŲ duomenų), tada filtras pagal datą
# ------------------------------------------------------------
inv_docs_all = build_doc_level(inv_raw, inv_id, inv_date_col)
crn_docs_all = build_doc_level(crn_raw, crn_id, crn_date_col) if (crn_raw is not None and crn_id and crn_date_col) else None

# Filtras taikomas DOC lygiui (NE eilutėms) – nebesumigravęs į „sausį“
inv_docs = inv_docs_all.loc[inv_docs_all["Data"].dt.date.between(nuo, iki)].copy()
crn_docs = crn_docs_all.loc[crn_docs_all["Data"].dt.date.between(nuo, iki)].copy() if crn_docs_all is not None else None

if inv_docs.empty and (crn_docs is None or crn_docs.empty):
    st.info("Pasirinktame laikotarpyje dokumentų nerasta.")
    st.stop()

# ------------------------------------------------------------
# Kiekiai per periodus (unikalūs dokumentai)
# ------------------------------------------------------------
inv_cnt = counts_unique_docs(inv_docs.rename(columns={inv_id: "DOC_ID"}), "DOC_ID", gran)
crn_cnt = counts_unique_docs(crn_docs.rename(columns={crn_id: "DOC_ID"}), "DOC_ID", gran) if (crn_docs is not None and not crn_docs.empty) else pd.DataFrame(columns=["Periodas","Kiekis"])

all_cnt = (
    pd.merge(inv_cnt, crn_cnt, how="outer", on="Periodas", suffixes=("_inv", "_crn"))
      .fillna(0)
)
all_cnt["Kiekis"] = (all_cnt["Kiekis_inv"] - all_cnt["Kiekis_crn"]) if crn_negative else (all_cnt["Kiekis_inv"] + all_cnt["Kiekis_crn"])
all_cnt = all_cnt[["Periodas","Kiekis"]].sort_values("Periodas").reset_index(drop=True)

if all_cnt.empty:
    st.info("Pasirinktame laikotarpyje dokumentų nerasta.")
    st.stop()

# ------------------------------------------------------------
# Grafikas
# ------------------------------------------------------------
st.subheader("Kiekis per periodus")

plot_df = all_cnt.copy()
plot_df["Pradzia"] = plot_df["Periodas"].apply(lambda p: period_start_ts(p, gran))
plot_df = plot_df.dropna(subset=["Pradzia"]).sort_values("Pradzia").reset_index(drop=True)

if show_ma:
    window = 3 if gran == "M" else 4
    plot_df["Slankus vidurkis"] = moving_average(plot_df["Kiekis"], window)

fig = go.Figure()
fig.add_bar(x=plot_df["Pradzia"], y=plot_df["Kiekis"], name=f"Kiekis per {'mėn.' if gran=='M' else 'sav.'}", marker_color="#00E5FF", opacity=0.45)
if show_ma:
    fig.add_scatter(x=plot_df["Pradzia"], y=plot_df["Slankus vidurkis"], name=f"Slankus vidurkis ({window} {'mėn.' if gran=='M' else 'sav.'})", mode="lines", line=dict(color="#76A9FA", width=3))

fig.update_layout(title="Išrašytų dokumentų kiekis per periodą", height=420, bargap=0.12, hovermode="x unified")
fig.update_xaxes(tickformat="%Y %b" if gran == "M" else "%Y-%m-%d", showgrid=True)
fig.update_yaxes(title_text="Dokumentų kiekis", rangemode="tozero", showgrid=True)

st.plotly_chart(fig, use_container_width=True)

# ------------------------------------------------------------
# KPI (unikalūs dokumentai) – čia ir pamatysi 18 vietoje 211
# ------------------------------------------------------------
total_inv = int(inv_docs.shape[0]) if inv_docs is not None else 0
total_crn = int(crn_docs.shape[0]) if (crn_docs is not None) else 0
total_net = int(all_cnt["Kiekis"].sum())

k1, k2, k3 = st.columns(3)
k1.metric("Sąskaitų kiekis (unikalūs)", f"{total_inv:,}".replace(",", " "))
k2.metric("Kreditinių kiekis (unikalūs)", f"{total_crn:,}".replace(",", " "))
k3.metric(("Grynas kiekis (su minusu)" if crn_negative else "Bendras kiekis (inv+crn)"), f"{total_net:,}".replace(",", " "))

# ------------------------------------------------------------
# Diagnostika – kad užmuštume klaidą vietoje
# ------------------------------------------------------------
with st.expander("🔎 Diagnostika (paspausk jei reikia)"):
    st.write("Laikotarpis:", f"{nuo} – {iki}")
    st.write("INV ID:", inv_id, "| INV DATA:", inv_date_col, "| INV doc #:", len(inv_docs_all))
    st.write("CRN ID:", crn_id, "| CRN DATA:", crn_date_col, "| CRN doc # (po prefikso filtro):", 0 if crn_docs_all is None else len(crn_docs_all))
    if crn_raw is not None and crn_id in crn_raw.columns:
        # parodyti top prefiksus pačiam pasitikrinti
        pref = crn_raw[crn_id].astype(str).str.upper().str.strip().str.extract(r'^([A-Z]+)')[0].value_counts().head(10)
        st.write("CRN prefiksų TOP (po filtro COP|KRE|AAA):")
        st.dataframe(pref)
    if crn_docs_all is not None:
        st.write("CRN mėnesių skirstinys (iš VISŲ duomenų po prefikso filtro):")
        st.dataframe(crn_docs_all.assign(M=lambda d: d["Data"].dt.to_period("M").astype(str)).M.value_counts().sort_index())
