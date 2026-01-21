import streamlit as st
import pandas as pd
import numpy as np
from io import BytesIO
from decimal import Decimal, ROUND_DOWN

st.header("🧾 Likučiai ir planai")

def floor2(x):
    try:
        d = Decimal(str(x)); return float(d.quantize(Decimal("0.01"), rounding=ROUND_DOWN))
    except: return np.nan

inv = st.session_state.get("inv_norm")
crn = st.session_state.get("crn_norm")

if inv is None:
    st.warning("Įkelk duomenis skiltyje **📥 Įkėlimas**.")
    st.stop()

# Sumos pagal sutartį
inv_sum = inv.groupby(["Klientas","SutartiesID"], dropna=False)["Suma_be_PVM"].sum().rename("Pajamuota").reset_index()
if crn is not None and not crn.empty:
    crn_sum = crn.groupby(["Klientas","SutartiesID"], dropna=False)["Suma_be_PVM"].sum().rename("Kredituota").reset_index()
else:
    crn_sum = pd.DataFrame(columns=["Klientas","SutartiesID","Kredituota"])

fact = pd.merge(inv_sum, crn_sum, how="outer", on=["Klientas","SutartiesID"]).fillna(0.0)
fact["Faktas"] = fact["Pajamuota"] + fact["Kredituota"]

# Planai (editable)
if "plans" not in st.session_state:
    base = fact[["Klientas","SutartiesID"]].drop_duplicates()
    base["SutartiesPlanas"] = 0.0
    st.session_state["plans"] = base

st.subheader("✍️ Įvesk sutarčių planus")
plans = st.data_editor(
    st.session_state["plans"].sort_values(["Klientas","SutartiesID"]).reset_index(drop=True),
    num_rows="dynamic",
    use_container_width=True,
    column_config={
        "SutartiesPlanas": st.column_config.NumberColumn("Sutarties suma (planas) €", step=0.01, format="%.2f")
    }
)
st.session_state["plans"] = plans

# Likučiai
out = pd.merge(plans, fact, how="left", on=["Klientas","SutartiesID"]).fillna(0.0)
out["Pajamuota"] = out["Pajamuota"].apply(floor2)
out["Kredituota"] = out["Kredituota"].apply(floor2)
out["Faktas"] = out["Faktas"].apply(floor2)
out["Likutis"] = (out["SutartiesPlanas"] - out["Faktas"]).apply(floor2)
out["Statusas"] = np.where(out["Likutis"] < 0, "🔴 Viršyta", np.where(out["Likutis"]==0, "🟡 Išnaudyta", "🟢 Dar liko"))

c1,c2,c3,c4 = st.columns(4)
c1.metric("Pajamuota €", f"{out['Pajamuota'].sum():,.2f}")
c2.metric("Kredituota €", f"{out['Kredituota'].sum():,.2f}")
c3.metric("Faktas €", f"{out['Faktas'].sum():,.2f}")
c4.metric("Likutis €", f"{out['Likutis'].sum():,.2f}")

st.subheader("Sutarčių likučiai")
st.dataframe(out.sort_values(["Klientas","SutartiesID"]), use_container_width=True)

# Eksportas į Excel
buf = BytesIO()
with pd.ExcelWriter(buf, engine="openpyxl") as xw:
    out.to_excel(xw, sheet_name="Sutarciu_likuciai", index=False)
    inv.to_excel(xw, sheet_name="Saskaitos_filtruotos", index=False)
    if crn is not None and not crn.empty:
        crn.to_excel(xw, sheet_name="Kreditines_filtruotos", index=False)

st.download_button("⬇️ Eksportuoti suvestinę (.xlsx)", data=buf.getvalue(),
                   file_name="sutarciu_likuciai.xlsx",
                   mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
