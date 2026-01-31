import streamlit as st

# Globali sargyba visiems multipage puslapiams
if not st.session_state.get("logged_in", False):
    # Pasirinktinai – pranešimas (neprivaloma)
    st.warning("Reikia prisijungti.")
    # Grąžinam į pagrindinį puslapį su login forma
    st.switch_page("app.py")   # svarbu: kelias į tavo startinį failą


# pages/3_📈_MoM_WoW_kiekiai.py

import pandas as pd
import numpy as np
from datetime import date

st.header("📈 Dokumentų kiekio dinamika (MoM & WoW)")

# ===================== Pagalbinės =====================

def ensure_df(src):
    """Tikimės DataFrame iš Įkėlimo puslapio."""
    if src is None:
        return None
    return src if isinstance(src, pd.DataFrame) else None

def pick_id_column(df: pd.DataFrame) -> str | None:
    """
    Randa dokumento ID stulpelį:
    Pirmenybė: 'Saskaitos_NR', bet palaikomi ir kiti dažni pavadinimai.
    """
    if df is None or df.empty:
        return None
    candidates = [
        "Saskaitos_NR", "SaskaitosNr", "InvoiceNo",
        "Dok_ID", "DokID", "Dokumento_Nr", "DokumentoNr",
        "DokNumeris", "Numeris", "No"
    ]
    cols = set(df.columns)
    for c in candidates:
        if c in cols:
            return c
    return None

def to_period_series(s: pd.Series, granularity: str) -> pd.Series:
    """pandas Period: 'M' arba 'W-MON' -> str (gražiai grupavimui ir lentelei)."""
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

def counts(df: pd.DataFrame, id_col: str, granularity: str) -> pd.DataFrame:
    """
    Grąžina DF su stulpeliais: Periodas, Kiekis
    - granularity: 'M' arba 'W'
    """
    d = df.copy()
    d["Data"] = pd.to_datetime(d["Data"], errors="coerce")
    d = d.dropna(subset=["Data"])
    if d.empty:
        return pd.DataFrame(columns=["Periodas", "Kiekis"])
    period = to_period_series(d["Data"], "M" if granularity == "M" else "W")
    x = (
        d.assign(Periodas=period)
         .groupby("Periodas")[id_col]
         .nunique()
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
    dates = pd.concat([d["Data"] for d in dfs if d is not None and "Data" in d.columns], axis=0)
    dates = pd.to_datetime(dates, errors="coerce").dropna()
    if dates.empty:
        today = pd.Timestamp.today().normalize()
        return today, today
    return dates.min().normalize(), dates.max().normalize()

# ===================== Duomenys iš sesijos =====================

inv = ensure_df(st.session_state.get("inv_norm"))
crn = ensure_df(st.session_state.get("crn_norm"))

if inv is None:
    st.warning("Įkelk duomenis skiltyje **📥 Įkėlimas**.")
    st.stop()

# Tipų sanitarija
frames = [inv] if crn is None else [inv, crn]
for df in frames:
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
mask_inv = inv["Data"].dt.date.between(nuo, iki)
inv_f = inv.loc[mask_inv].copy()

crn_f = None
if crn is not None:
    mask_crn = crn["Data"].dt.date.between(nuo, iki)
    crn_f = crn.loc[mask_crn].copy()

if inv_f.empty and (crn_f is None or crn_f.empty):
    st.info("Pasirinktame laikotarpyje dokumentų nerasta.")
    st.stop()

# ===================== ID stulpelis =====================

id_col_inv = pick_id_column(inv_f)
id_col_crn = pick_id_column(crn_f) if crn_f is not None and not crn_f.empty else None

if id_col_inv is None and (crn_f is None or id_col_crn is None):
    with st.expander("Diagnostika: trūksta dokumento Nr. stulpelio"):
        st.write("Ieškojau stulpelių: 'Saskaitos_NR', 'SaskaitosNr', 'InvoiceNo', 'Dok_ID', 'Dokumento_Nr' ir kt.")
        st.write("inv_f stulpeliai:", list(inv_f.columns))
        if crn_f is not None:
            st.write("crn_f stulpeliai:", list(crn_f.columns))
    st.error("Nerastas dokumento numerio stulpelis. Įkėlime naudok A,B,D,F,G schemą arba pervardink į 'Saskaitos_NR'.")
    st.stop()

# ===================== Kiekiai per periodus =====================

inv_cnt = counts(inv_f, id_col_inv, gran) if id_col_inv else pd.DataFrame(columns=["Periodas","Kiekis"])
if crn_f is not None and not crn_f.empty and id_col_crn:
    crn_cnt = counts(crn_f, id_col_crn, gran)
else:
    crn_cnt = pd.DataFrame(columns=["Periodas","Kiekis"])

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

# ===================== Grafikas (be papildomų priklausomybių) =====================

st.subheader("Kiekis per periodus")

# Paruošiam grafiko ašį – periodo pradžios data
plot_df = all_cnt.copy()
plot_df["Pradzia"] = plot_df["Periodas"].apply(lambda p: period_start_ts(p, gran))
plot_df = plot_df.dropna(subset=["Pradzia"]).sort_values("Pradzia").reset_index(drop=True)

# Slankus vidurkis
if show_ma:
    window = 3 if gran == "M" else 4
    plot_df["Slankus vidurkis"] = moving_average(plot_df["Kiekis"], window)

# Built-in linijinė diagrama
chart_df = plot_df.set_index("Pradzia")[["Kiekis"]].copy()
if show_ma:
    chart_df["Slankus vidurkis"] = plot_df.set_index("Pradzia")["Slankus vidurkis"]

st.line_chart(chart_df, height=320, use_container_width=True)

# ===================== KPI =====================

total_inv = int(inv_cnt["Kiekis"].sum()) if not inv_cnt.empty else 0
total_crn = int(crn_cnt["Kiekis"].sum()) if not crn_cnt.empty else 0
total_net = int(all_cnt["Kiekis"].sum())

k1, k2, k3 = st.columns(3)
k1.metric("Sąskaitų kiekis", f"{total_inv:,}".replace(",", " "))
k2.metric("Kreditinių kiekis", f"{total_crn:,}".replace(",", " "))
k3.metric(("Grynas kiekis (su minusu)" if crn_negative else "Bendras kiekis (inv+crn)"),
          f"{total_net:,}".replace(",", " "))

# ===================== Lentelė =====================

st.subheader("Lentelė")
table_cols = ["Periodas", "Kiekis"] + (["Slankus vidurkis"] if show_ma else [])
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
    st.write("Pirmos inv_f eilutės:")
    st.dataframe(inv_f.head())
    if crn_f is not None and not crn_f.empty:
        st.write("Pirmos crn_f eilutės:")
        st.dataframe(crn_f.head())
