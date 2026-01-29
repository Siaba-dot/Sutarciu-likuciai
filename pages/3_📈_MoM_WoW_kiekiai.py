import streamlit as st
import pandas as pd
import numpy as np
from datetime import date

st.header("📈 Dokumentų kiekio dinamika (MoM & WoW)")

# ========= Pagalbinės =========
def ensure_df(src):
    if src is None:
        return None
    return src if isinstance(src, pd.DataFrame) else None

def pick_id_column(df: pd.DataFrame) -> str | None:
    """
    Bando rasti dokumento ID stulpelį keliomis versijomis.
    Pirmenybė: 'Saskaitos_NR', vėliau – alternatyvūs pavadinimai.
    """
    candidates = [
        "Saskaitos_NR", "SaskaitosNr", "InvoiceNo", "Dok_ID", "DokID", "Dokumento_Nr",
        "DokumentoNr", "DokNumeris", "Numeris", "No"
    ]
    cols = set(df.columns)
    for c in candidates:
        if c in cols:
            return c
    # jei neranda – grąžina None
    return None

def counts(df: pd.DataFrame, id_col: str, granularity: str) -> pd.DataFrame:
    """
    Grąžina DF su stulpeliais: Periodas, Kiekis
    granularity: 'M' (mėnuo) arba 'W' (savaitė, ISO savaitė)
    """
    d = df.copy()
    d["Data"] = pd.to_datetime(d["Data"], errors="coerce")
    d = d.dropna(subset=["Data"])

    if granularity == "M":
        period = d["Data"].dt.to_period("M").astype(str)  # YYYY-MM
    else:
        # ISO savaitės numeris (YYYY-Www)
        # Pastaba: to_period('W-MON') gražiai sulaužo savaitėmis nuo pirmadienio
        period = d["Data"].dt.to_period("W-MON").astype(str)

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
    return series.rolling(window=window, min_periods=1).mean()

def min_max_date(*dfs):
    dates = pd.concat([d["Data"] for d in dfs if d is not None and "Data" in d.columns], axis=0)
    dates = pd.to_datetime(dates, errors="coerce").dropna()
    if dates.empty:
        today = pd.Timestamp.today().normalize()
        return today, today
    return dates.min().normalize(), dates.max().normalize()

# ========= Duomenys iš sesijos =========
inv = ensure_df(st.session_state.get("inv_norm"))
crn = ensure_df(st.session_state.get("crn_norm"))

if inv is None:
    st.warning("Įkelk duomenis skiltyje **📥 Įkėlimas**.")
    st.stop()

# Tipų sanitarija
frames = [inv] if crn is None else [inv, crn]
for df in frames:
    df["Data"] = pd.to_datetime(df["Data"], errors="coerce")
    # Jei naudotojas netyčia įmetė kitą pavadinimą – susikuriam 'Saskaitos_NR' dublerį diagnostikai
    if "Saskaitos_NR" not in df.columns:
        pass  # realiai 'pick_id_column' pats suras tinkamą stulpelį

# ========= UI: Periodiškumas & slankus vidurkis =========
st.subheader("Periodiškumas")
gran = st.radio(" ", options=["Mėnuo (MoM)", "Savaitė (WoW)"], horizontal=True, index=0)
gran_key = "M" if "Mėnuo" in gran else "W"

show_ma = st.toggle("Rodyti slankų vidurkį (3 mėn. / 4 sav.)", value=True)

# ========= Laikotarpis =========
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

# Filtruojam datas
mask_inv = inv["Data"].dt.date.between(nuo, iki)
inv_f = inv.loc[mask_inv].copy()
crn_f = None
if crn is not None:
    mask_crn = crn["Data"].dt.date.between(nuo, iki)
    crn_f = crn.loc[mask_crn].copy()

if inv_f.empty and (crn_f is None or crn_f.empty):
    st.info("Pasirinktame laikotarpyje dokumentų nerasta.")
    st.stop()

# ========= ID stulpelis (automatinė paieška) =========
id_col_inv = pick_id_column(inv_f)
id_col_crn = pick_id_column(crn_f) if crn_f is not None and not crn_f.empty else None

missing = []
if id_col_inv is None:
    missing.append("Sąskaitoms (inv)")
if crn_f is not None and not crn_f.empty and id_col_crn is None:
    missing.append("Kreditinėms (crn)")

if missing:
    with st.expander("Diagnostika: trūksta dokumento Nr. stulpelio"):
        st.write("Neradau šių rinkinų ID stulpelio (ieškoti bandžiau: 'Saskaitos_NR', 'SaskaitosNr', 'InvoiceNo', 'Dok_ID' ir kt.).")
        st.write("inv_f stulpeliai:", list(inv_f.columns))
        if crn_f is not None:
            st.write("crn_f stulpeliai:", list(crn_f.columns))
    st.error("Nerastas dokumento numerio stulpelis. Įkėlime naudok A,B,D,F,G schemą arba pervardink stulpelį į 'Saskaitos_NR'.")
    st.stop()

# ========= Kiekiai =========
inv_cnt = counts(inv_f, id_col_inv, gran_key) if id_col_inv else pd.DataFrame(columns=["Periodas","Kiekis"])
if crn_f is not None and not crn_f.empty and id_col_crn:
    crn_cnt = counts(crn_f, id_col_crn, gran_key)
else:
    crn_cnt = pd.DataFrame(columns=["Periodas","Kiekis"])

# Sujungiame: +Kreditinės skaičiuojamos kaip atskirų dokumentų kiekis
all_cnt = (
    pd.merge(inv_cnt, crn_cnt, how="outer", on="Periodas", suffixes=("_inv","_crn"))
      .fillna(0)
      .assign(Kiekis=lambda d: d["Kiekis_inv"] + d["Kiekis_crn"])
      [["Periodas","Kiekis"]]
      .sort_values("Periodas")
      .reset_index(drop=True)
)

if all_cnt.empty:
    st.info("Pasirinktame laikotarpyje dokumentų nerasta.")
    st.stop()

# ========= Braižymas =========
st.subheader("Kiekis per periodus")

# Kad vartotojui būtų patogu – paverskim Periodas į datetime pradžią (vizualiai tvarkingiau)
def parse_period_start(p: str) -> pd.Timestamp:
    try:
        if gran_key == "M":
            return pd.Period(p, freq="M").start_time
        else:
            return pd.Period(p, freq="W-MON").start_time
    except Exception:
        return pd.NaT

plot_df = all_cnt.copy()
plot_df["Pradzia"] = plot_df["Periodas"].apply(parse_period_start)
plot_df = plot_df.dropna(subset=["Pradzia"]).sort_values("Pradzia").reset_index(drop=True)

if show_ma:
    window = 3 if gran_key == "M" else 4
    plot_df["Slankus_vidurkis"] = moving_average(plot_df["Kiekis"], window)

# Paprastas linijinis grafikas (be Altair, kad nekibtų priklausomybės)
import matplotlib.pyplot as plt

fig, ax = plt.subplots(figsize=(8, 3))
ax.plot(plot_df["Pradzia"], plot_df["Kiekis"], marker="o", label="Kiekis")
if show_ma:
    ax.plot(plot_df["Pradzia"], plot_df["Slankus_vidurkis"], color="tab:orange", linewidth=2, label="Slankus vidurkis")

ax.set_title("Dokumentų kiekis per periodus")
ax.set_xlabel("Periodas")
ax.set_ylabel("Kiekis (vnt.)")
ax.grid(True, alpha=0.3)
ax.legend()
st.pyplot(fig)

# Rodome ir lentelę
st.subheader("Lentelė")
st.dataframe(plot_df[["Periodas","Kiekis"] + (["Slankus_vidurkis"] if show_ma else [])], use_container_width=True)
