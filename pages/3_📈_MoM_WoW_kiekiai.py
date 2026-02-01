    # pages/3_📈_MoM_WoW_kiekiai.py
import streamlit as st
import pandas as pd
import numpy as np
from datetime import date

# --- Plotly: tema ---
import plotly.graph_objects as go
import plotly.io as pio

# Vieną kartą puslapio config
st.set_page_config(layout="wide")

# --- Kompaktinis tamsus išdėstymas: mažesni tarpai ir antraščių dydžiai ---
st.markdown("""
<style>
  /* Pagrindinio konteinerio tarpai ir maksimalus plotis */
  .block-container {padding-top: 0.5rem; padding-bottom: 0.75rem; max-width: 1500px;}

  /* Paslepiam/kompaktinam Streamlit viršutinį header */
  header[data-testid="stHeader"] {height: 0rem; visibility: hidden;}

  /* Mažesni H1/H2, kad neužliptų ir tilptų */
  h1, .stMarkdown h1 {font-size: 1.55rem; line-height: 1.2; margin: 0.2rem 0 0.6rem 0;}
  h2, .stMarkdown h2 {font-size: 1.25rem; line-height: 1.25; margin: 0.1rem 0 0.4rem 0;}
  h3, .stMarkdown h3 {font-size: 1.05rem; line-height: 1.25; margin: 0.1rem 0 0.3rem 0;}

  /* Mažesni vertikalūs tarpai tarp valdiklių */
  div[data-testid="stVerticalBlock"] > div:has(.stRadio), 
  div[data-testid="stVerticalBlock"] > div:has(.stDateInput),
  div[data-testid="stVerticalBlock"] > div:has(.stToggle) {margin-top: 0.25rem; margin-bottom: 0.25rem;}

  /* Kompaktinis legendas Plotly (užims mažiau aukščio) */
  .modebar {transform: scale(0.95); transform-origin: top right;}
</style>
""", unsafe_allow_html=True)

# Vieningas tamsus/neon šablonas „wow“
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

# --- Puslapio UI ---
st.header("📈 Dokumentų kiekio dinamika (MoM & WoW)")

# ===================== Pagalbinės =====================

def ensure_df(src):
    """Tikimės DataFrame iš Įkėlimo puslapio."""
    return src if isinstance(src, pd.DataFrame) else None

def pick_id_column_strict(df: pd.DataFrame) -> str | None:
    """
    Grąžina dokumento numerio stulpelį.
    * Griežta tvarka – NEIMAME generinių ('Numeris', 'No', 'Dok_ID'), nes jie dažnai eilučių ID.
    Pirmenybė:
      - 'Saskaitos_NR', 'SaskaitosNr', 'InvoiceNo'
      - 'Dokumento_Nr', 'DokumentoNr'
    """
    if df is None or df.empty:
        return None
    prefer = ["Saskaitos_NR", "SaskaitosNr", "InvoiceNo", "Dokumento_Nr", "DokumentoNr"]
    cols = set(df.columns)
    for c in prefer:
        if c in cols:
            return c
    return None  # jei neradom – geriau sustabdyti su diagnostika, nei suskaičiuoti nesąmones

def to_period_series(s: pd.Series, granularity: str) -> pd.Series:
    """pandas Period: 'M' arba 'W-MON' -> str (grupavimui ir lentelei)."""
    if granularity == "M":
        return s.dt.to_period("M").astype(str)        # YYYY-MM
    else:
        return s.dt.to_period("W-MON").astype(str)    # ISO savaitės, pirmadieniais

def period_start_ts(p: str, granularity: str) -> pd.Timestamp:
    """Parsuoja Period string į periodo pradžios laiką (grafikui)."""
    try:
        if granularity == "M":
            return pd.Period(p, freq="M").start_time
        else:
            return pd.Period(p, freq="W-MON").start_time
    except Exception:
        return pd.NaT

def counts_unique_docs(df: pd.DataFrame, id_col: str, granularity: str) -> pd.DataFrame:
    """
    Grąžina DF su stulpeliais: Periodas, Kiekis
    Skaičiuoja UNIKALIUS dokumentus per periodą – ignoruoja eilučių dublikatus.
    """
    d = df.copy()
    d["Data"] = pd.to_datetime(d["Data"], errors="coerce")
    d = d.dropna(subset=["Data", id_col])
    if d.empty:
        return pd.DataFrame(columns=["Periodas", "Kiekis"])
    # jei df ateina „eilutėmis“, dublikuoto docID per tą patį periodą nebedidins kiekio
    d["Periodas"] = to_period_series(d["Data"], "M" if granularity == "M" else "W")
    d = d.drop_duplicates(subset=["Periodas", id_col])  # ← svarbu
    x = (
        d.groupby("Periodas")[id_col]
         .size()
         .reset_index(name="Kiekis")
         .sort_values("Periodas")
         .reset_index(drop=True)
    )
    return x

def moving_average(series: pd.Series, window: int) -> pd.Series:
    """Slankus vidurkis su min_periods=1 (rodo nuo pirmų taškų)."""
    return series.rolling(window=window, min_periods=1).mean()

def min_max_date(*dfs):
    """Grąžina min/max datą per pateiktus DF (Data stulpelis)."""
    frames = [d for d in dfs if d is not None and "Data" in d.columns and not d.empty]
    if not frames:
        today = pd.Timestamp.today().normalize()
        return today, today
    dates = pd.concat([pd.to_datetime(d["Data"], errors="coerce") for d in frames], axis=0)
    dates = dates.dropna()
    if dates.empty:
        today = pd.Timestamp.today().normalize()
        return today, today
    return dates.min().normalize(), dates.max().normalize()

def aggregate_docs(df: pd.DataFrame, id_col: str) -> pd.DataFrame:
    """
    Iš eilutinių duomenų padaro dokumentų lygį: 1 eilutė = 1 dokumentas (pagal id_col).
    - Data: mažiausia (pirma) pagal dokumentą
    - Paliekam tik reikalingus laukus (Data, id_col)
    """
    if df is None or df.empty or id_col is None:
        return pd.DataFrame(columns=["Data", id_col])
    d = df.copy()
    d["Data"] = pd.to_datetime(d["Data"], errors="coerce")
    d = d.dropna(subset=["Data", id_col])
    out = (
        d.groupby(id_col, as_index=False)["Data"]
         .min()  # dokumento data – pirmoji (tinka skaičiavimui per periodus)
    )
    return out

# ===================== Duomenys iš sesijos =====================

# Tikimės, kad Įkėlimas puslapis paruošia normalizuotus DF:
#   st.session_state["inv_norm"]  – sąskaitos
#   st.session_state["crn_norm"]  – kreditinės (galimai tuščia)
inv = ensure_df(st.session_state.get("inv_norm"))
crn = ensure_df(st.session_state.get("crn_norm"))

if inv is None:
    st.warning("Įkelk duomenis skiltyje **📥 Įkėlimas**.")
    st.stop()

# Tipų sanitarija
frames = [inv] if crn is None else [inv, crn]
for df in frames:
    if "Data" in df.columns:
        df["Data"] = pd.to_datetime(df["Data"], errors="coerce")

# ===================== UI: Periodiškumas, slankus, laikotarpis =====================

st.subheader("Periodiškumas")
gran_label = st.radio(" ", options=["Mėnuo (MoM)", "Savaitė (WoW)"], horizontal=True, index=0)
gran = "M" if "Mėnuo" in gran_label else "W"

col_sw1, col_sw2 = st.columns([1,1])
with col_sw1:
    show_ma = st.toggle("Rodyti slankų vidurkį (3 mėn. / 4 sav.)", value=True)
with col_sw2:
    crn_negative = st.toggle("Kreditines skaičiuoti su minusu", value=False)

# Laikotarpis
dmin, dmax = min_max_date(inv, crn)
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

# Filtravimas pagal datą
mask_inv = inv["Data"].dt.date.between(nuo, iki) if "Data" in inv.columns else pd.Series(True, index=inv.index)
inv_f = inv.loc[mask_inv].copy()

crn_f = None
if crn is not None:
    mask_crn = crn["Data"].dt.date.between(nuo, iki) if "Data" in crn.columns else pd.Series(True, index=crn.index)
    crn_f = crn.loc[mask_crn].copy()

if inv_f.empty and (crn_f is None or crn_f.empty):
    st.info("Pasirinktame laikotarpyje dokumentų nerasta.")
    st.stop()

# ===================== ID stulpelis (griežtas) =====================

id_col_inv = pick_id_column_strict(inv_f)
id_col_crn = pick_id_column_strict(crn_f) if crn_f is not None and not crn_f.empty else None

if id_col_inv is None:
    with st.expander("Diagnostika: neradau dokumento Nr. stulpelio INV"):
        st.write("Ieškojau stulpelių: 'Saskaitos_NR', 'SaskaitosNr', 'InvoiceNo', 'Dokumento_Nr', 'DokumentoNr'.")
        st.write("inv_f stulpeliai:", list(inv_f.columns))
    st.error("Nerastas INV dokumento numerio stulpelis. Pervardink į 'Saskaitos_NR' arba pridėk vieną iš palaikomų.")
    st.stop()

if crn_f is not None and not crn_f.empty and id_col_crn is None:
    with st.expander("Diagnostika: neradau dokumento Nr. stulpelio CRN"):
        st.write("Ieškojau stulpelių: 'Saskaitos_NR', 'SaskaitosNr', 'InvoiceNo', 'Dokumento_Nr', 'DokumentoNr'.")
        st.write("crn_f stulpeliai:", list(crn_f.columns))
    st.error("Nerastas CRN dokumento numerio stulpelis. Pervardink į 'Saskaitos_NR' arba pridėk vieną iš palaikomų.")
    st.stop()

# ===================== Kiekiai per periodus (unikalūs dokumentai) =====================

# INV: skaičiuojam pagal dokumento lygį (unikalūs doc ID per periodą)
inv_docs = aggregate_docs(inv_f, id_col_inv)
inv_cnt  = counts_unique_docs(inv_docs, id_col_inv, gran)

# CRN: jei yra – pirmiausia agreguojame į dokumentų lygį, tada skaičiuojame
if crn_f is not None and not crn_f.empty and id_col_crn:
    crn_docs = aggregate_docs(crn_f, id_col_crn)
    crn_cnt  = counts_unique_docs(crn_docs, id_col_crn, gran)
else:
    crn_docs = pd.DataFrame(columns=["Data", id_col_crn if id_col_crn else "ID"])
    crn_cnt  = pd.DataFrame(columns=["Periodas","Kiekis"])

# sujungimas
all_cnt = (
    pd.merge(inv_cnt, crn_cnt, how="outer", on="Periodas", suffixes=("_inv", "_crn"))
      .fillna(0)
)

# Kiekio logika: +inv, +/-crn
if crn_negative:
    all_cnt["Kiekis"] = all_cnt["Kiekis_inv"] - all_cnt["Kiekis_crn"]
else:
    all_cnt["Kiekis"] = all_cnt["Kiekis_inv"] + all_cnt["Kiekis_crn"]

all_cnt = all_cnt[["Periodas", "Kiekis"]].sort_values("Periodas").reset_index(drop=True)

if all_cnt.empty:
    st.info("Pasirinktame laikotarpyje dokumentų nerasta.")
    st.stop()

# ===================== Grafikas (stulpeliniai + linija) =====================

st.subheader("Kiekis per periodus")

# Paruošiam grafiko ašį – periodo pradžios data
plot_df = all_cnt.copy()
plot_df["Pradzia"] = plot_df["Periodas"].apply(lambda p: period_start_ts(p, gran))
plot_df = plot_df.dropna(subset=["Pradzia"]).sort_values("Pradzia").reset_index(drop=True)

# Slankus vidurkis
if show_ma:
    window = 3 if gran == "M" else 4
    plot_df["Slankus vidurkis"] = moving_average(plot_df["Kiekis"], window)

# Bar + line figūra (Plotly)
fig = go.Figure()

# Stulpeliai: dokumentų kiekis per periodą (MoM arba WoW)
fig.add_bar(
    x=plot_df["Pradzia"],
    y=plot_df["Kiekis"],
    name=f"Kiekis per {'mėn.' if gran=='M' else 'sav.'}",
    marker_color="#00E5FF",
    opacity=0.45,
)

# Linija: slankus vidurkis (jei įjungtas)
if show_ma:
    fig.add_scatter(
        x=plot_df["Pradzia"],
        y=plot_df["Slankus vidurkis"],
        name=f"Slankus vidurkis ({window} {'mėn.' if gran=='M' else 'sav.'})",
        mode="lines",
        line=dict(color="#76A9FA", width=3),
    )

fig.update_layout(
    title="Išrašytų dokumentų kiekis per periodą",
    height=420,
    bargap=0.12,
    hovermode="x unified",
)
fig.update_xaxes(
    tickformat="%Y %b" if gran == "M" else "%Y-%m-%d",
    showgrid=True,
)
fig.update_yaxes(
    title_text="Dokumentų kiekis",
    rangemode="tozero",
    showgrid=True,
)

st.plotly_chart(fig, use_container_width=True)

# ===================== KPI =====================

# KPI skaičiuojam iš dokumentų lygio (unikalūs), o ne sumą per periodus
total_inv = int(inv_docs[id_col_inv].nunique()) if not inv_docs.empty else 0
total_crn = int(crn_docs[id_col_crn].nunique()) if not crn_docs.empty and id_col_crn else 0
# Grynas/bendras kiekis – skaičiuojam taip pat iš sujungtų per periodus, bet tai informacinė metrika:
total_net = int(all_cnt["Kiekis"].sum())

k1, k2, k3 = st.columns(3)
k1.metric("Sąskaitų kiekis (unikalūs)", f"{total_inv:,}".replace(",", " "))
k2.metric("Kreditinių kiekis (unikalūs)", f"{total_crn:,}".replace(",", " "))
k3.metric(("Grynas kiekis (su minusu)" if crn_negative else "Bendras kiekis (inv+crn)"),
          f"{total_net:,}".replace(",", " "))

# ===================== Lentelė =====================

st.subheader("Lentelė")
display_df = plot_df[["Periodas", "Kiekis"] + (["Slankus vidurkis"] if show_ma else [])].copy()
st.dataframe(display_df, use_container_width=True)

# ===================== Diagnostika (paslėpta) =====================

with st.expander("🔎 Diagnostika (paspausk jei reikia)"):
    st.write("Granuliavimas:", "Mėnesis" if gran == "M" else "Savaitė")
    st.write("Laikotarpis:", f"{nuo} – {iki}")
    st.write("Naudotas ID (inv):", id_col_inv)
    st.write("Naudotas ID (crn):", id_col_crn)
    st.write("inv_f eilutės:", len(inv_f))
    st.write("crn_f eilutės:", 0 if crn_f is None else len(crn_f))
    st.write("INV dokumentų (unikalūs):", total_inv)
    st.write("CRN dokumentų (unikalūs):", total_crn)
    st.write("Pirmos inv_f eilutės:")
    st.dataframe(inv_f.head())
    if crn_f is not None and not crn_f.empty:
        st.write("Pirmos crn_f eilutės:")
        st.dataframe(crn_f.head())
