import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px

st.header("📈 Dokumentų kiekio dinamika (MoM & WoW)")

inv = st.session_state.get("inv_norm")
crn = st.session_state.get("crn_norm")

if inv is None and (crn is None or crn.empty):
    st.warning("Įkelk duomenis skiltyje **📥 Įkėlimas**.")
    st.stop()

gran = st.radio("Periodiškumas", ["Mėnuo (MoM)", "Savaitė (WoW)"], horizontal=True)
show_ma = st.toggle("Rodyti slankų vidurkį (3 mėn. / 4 sav.)", value=True)

def counts(df: pd.DataFrame, id_col: str, gran_: str):
    if df is None or df.empty:
        return pd.DataFrame(columns=["Periodas","Kiekis"])
    if gran_ == "Mėnuo (MoM)":
        x = df.assign(Periodas = df["Data"].dt.to_period("M").astype(str))               .groupby("Periodas")[id_col].nunique().reset_index(name="Kiekis")
        return x.sort_values("Periodas")
    else:
        iso = df["Data"].dt.isocalendar()
        lab = iso["year"].astype(str) + "-W" + iso["week"].astype(str).str.zfill(2)
        x = df.assign(Periodas = lab).groupby("Periodas")[id_col].nunique().reset_index(name="Kiekis")
        ord = df.assign(Periodas=lab).groupby("Periodas")["Data"].min().sort_values().index
        return x.set_index("Periodas").loc[ord].reset_index()

def pct_delta(series: pd.Series):
    if series is None or series.size < 2: return None
    last, prev = series.iloc[-1], series.iloc[-2]
    if prev == 0: return None
    return (last - prev) / prev * 100.0

inv_cnt = counts(inv, "SaskaitosNr", gran) if inv is not None else pd.DataFrame(columns=["Periodas","Kiekis"])
crn_cnt = counts(crn, "KreditinesNr", gran) if crn is not None else pd.DataFrame(columns=["Periodas","Kiekis"])

momwow = "WoW" if gran == "Savaitė (WoW)" else "MoM"

kpi1, kpi2, kpi3, kpi4 = st.columns(4)
kpi1.metric("Sąskaitų skaičius", f"{(inv_cnt['Kiekis'].iloc[-1] if len(inv_cnt)>0 else 0):,}".replace(",", " "))
kpi2.metric(f"{momwow} % (sąskaitos)", 
            f"{pct_delta(inv_cnt['Kiekis']):.1f}%" if len(inv_cnt)>1 and pct_delta(inv_cnt['Kiekis']) is not None else "—")
kpi3.metric("Kreditinių skaičius", f"{(crn_cnt['Kiekis'].iloc[-1] if len(crn_cnt)>0 else 0):,}".replace(",", " "))
kpi4.metric(f"{momwow} % (kreditinės)", 
            f"{pct_delta(crn_cnt['Kiekis']):.1f}%" if len(crn_cnt)>1 and pct_delta(crn_cnt['Kiekis']) is not None else "—")

inv_cnt["Tipas"] = "Sąskaitos"
crn_cnt["Tipas"] = "Kreditinės"
both = pd.concat([inv_cnt, crn_cnt], ignore_index=True)

st.subheader("📊 Kiekio dinamika")
fig = px.line(both, x="Periodas", y="Kiekis", color="Tipas", markers=True,
              title=f"Dokumentų kiekis per laiką – {gran}")
fig.update_layout(template="plotly_dark", hovermode="x unified")
st.plotly_chart(fig, use_container_width=True)

if show_ma and not both.empty:
    window = 3 if gran == "Mėnuo (MoM)" else 4
    both = both.sort_values(["Tipas","Periodas"])
    both["MA"] = both.groupby("Tipas")["Kiekis"].transform(lambda s: s.rolling(window, min_periods=1).mean())
    st.subheader(f"Slankus vidurkis ({window} {'mėn.' if window==3 else 'sav.'})")
    fig2 = px.line(both, x="Periodas", y="MA", color="Tipas", title="Slankus vidurkis")
    fig2.update_layout(template="plotly_dark", hovermode="x unified")
    st.plotly_chart(fig2, use_container_width=True)

colt1, colt2 = st.columns(2)
with colt1:
    st.write("Sąskaitų skaičius pagal periodą")
    st.dataframe(inv_cnt, use_container_width=True)
with colt2:
    st.write("Kreditinių skaičius pagal periodą")
    st.dataframe(crn_cnt, use_container_width=True)
