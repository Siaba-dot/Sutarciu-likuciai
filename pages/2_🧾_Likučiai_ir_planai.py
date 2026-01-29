import streamlit as st
import pandas as pd
import numpy as np
from io import BytesIO
from decimal import Decimal, ROUND_DOWN

st.header("🧾 Likučiai ir planai (sumos SU PVM)")

def floor2(x):
    try:
        return float(Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_DOWN))
    except:  # noqa: E722
        return 0.0

# --- NAUJA: užtikrinam nuskaitymą pagal raides ---
def read_by_letters(file_or_buf, 
                    col_map=("A","B","D","F","G"),
                    names=("Data","Saskaitos_NR","Klientas","SutartiesID","Suma")) -> pd.DataFrame:
    df = pd.read_excel(
        file_or_buf,
        header=None,
        engine="openpyxl",
        usecols=list(col_map)
    )
    df.columns = list(names)
    if "Data" in df.columns:
        df["Data"] = pd.to_datetime(df["Data"], errors="coerce")
    if "Suma" in df.columns:
        df["Suma"] = pd.to_numeric(df["Suma"], errors="coerce")
    for c in ("Klientas","SutartiesID","Saskaitos_NR"):
        if c in df.columns:
            df[c] = df[c].astype(str).str.strip()
    df["Suma_su_PVM"] = df["Suma"].fillna(0.0)
    return df

def ensure_df_from_source(src):
    if src is None:
        return None
    if isinstance(src, pd.DataFrame):
        # Jei jau DF, patikrinam ar turi reikiamus laukus; jei ne, bandysim „auto“ perskaityti
        required = {"Data","Saskaitos_NR","Klientas","SutartiesID","Suma_su_PVM"}
        if required.issubset(set(src.columns)):
            return src
        # Jeigu DF neteisingas (pvz., su blogais headeriais), neleisim slinkti toliau
        # rekomenduotina šaltinyje dėti failo objektą, bet pabandysim minimaliai sutvarkyti:
        df = src.copy()
        # Jei turi bent 5 stulpelius, paimsime pagal pozicijas (0=A,1=B,3=D,5=F,6=G)
        if df.shape[1] >= 7:
            df = df.iloc[:, [0,1,3,5,6]].copy()
            df.columns = ["Data","Saskaitos_NR","Klientas","SutartiesID","Suma"]
            df["Data"] = pd.to_datetime(df["Data"], errors="coerce")
            df["Suma"] = pd.to_numeric(df["Suma"], errors="coerce")
            for c in ("Klientas","SutartiesID","Saskaitos_NR"):
                df[c] = df[c].astype(str).str.strip()
            df["Suma_su_PVM"] = df["Suma"].fillna(0.0)
            return df
        return df  # tebūnie, bet vėliau faile matysis diagnostika
    # Jei src – tai įkeltas failo objektas (UploadedFile/BytesIO)
    return read_by_letters(src, col_map=("A","B","D","F","G"),
                                names=("Data","Saskaitos_NR","Klientas","SutartiesID","Suma"))

inv_src = st.session_state.get("inv_norm")
crn_src = st.session_state.get("crn_norm")

inv = ensure_df_from_source(inv_src)
crn = ensure_df_from_source(crn_src)

if inv is None:
    st.warning("Įkelk duomenis skiltyje **📥 Įkėlimas**.")
    st.stop()

# ——— Likęs tavo kodas be pakeitimų ———
# Sanitarija
frames = [inv] if crn is None else [inv, crn]
for df in frames:
    df["Klientas"] = df["Klientas"].astype(str).str.strip()
    if "SutartiesID" not in df.columns:
        df["SutartiesID"] = ""
    df["SutartiesID"] = df["SutartiesID"].astype(str).str.strip()

# Agregacijos SU PVM
inv_sum = (
    inv.groupby(["Klientas", "SutartiesID"], dropna=False)["Suma_su_PVM"]
    .sum()
    .rename("Israsyta")
    .reset_index()
)
if crn is not None and not crn.empty:
    crn_sum = (
        crn.groupby(["Klientas", "SutartiesID"], dropna=False)["Suma_su_PVM"]
        .sum()
        .rename("Kredituota")
        .reset_index()
    )
else:
    crn_sum = pd.DataFrame(columns=["Klientas", "SutartiesID", "Kredituota"])

fact = pd.merge(inv_sum, crn_sum, how="outer", on=["Klientas", "SutartiesID"]).fillna(0.0)
fact["Faktas"] = fact["Israsyta"] + fact["Kredituota"]

# Planai (editable)
if "plans" not in st.session_state:
    base = fact[["Klientas", "SutartiesID"]].drop_duplicates().copy()
    base["SutartiesPlanas"] = 0.0  # SU PVM
    st.session_state["plans"] = base

st.subheader("✍️ Įvesk sutarčių planus (SU PVM)")
plans = st.data_editor(
    st.session_state["plans"].sort_values(["Klientas", "SutartiesID"]).reset_index(drop=True),
    num_rows="dynamic",
    use_container_width=True,
    column_config={
        "Klientas": st.column_config.TextColumn(disabled=True),
        "SutartiesID": st.column_config.TextColumn(disabled=True),
        "SutartiesPlanas": st.column_config.NumberColumn(
            "Sutarties suma (planas) €", step=0.01, format="%.2f"
        ),
    },
)
plans["Klientas"] = plans["Klientas"].astype(str).str.strip()
plans["SutartiesID"] = plans["SutartiesID"].astype(str).str.strip()
st.session_state["plans"] = plans

# Likučiai
out = pd.merge(plans, fact, how="left", on=["Klientas", "SutartiesID"]).fillna(0.0)
out["Israsyta"] = out["Israsyta"].apply(floor2)
out["Kredituota"] = out["Kredituota"].apply(floor2)
out["Faktas"] = out["Faktas"].apply(floor2)
out["Like"] = (out["SutartiesPlanas"] - out["Faktas"]).apply(floor2)

# KPI (viso)
total_planas = floor2(out["SutartiesPlanas"].sum())
total_israsyta = floor2(out["Israsyta"].sum())
total_kred = floor2(out["Kredituota"].sum())
total_faktas = floor2(out["Faktas"].sum())
total_like = floor2(total_planas - total_faktas)
pct_total = 0.0 if total_planas == 0 else floor2((total_faktas / total_planas) * 100)

k1, k2, k3, k4 = st.columns(4)
k1.metric("Išrašyta € (su PVM)", f"{total_israsyta:,.2f}")
k2.metric("Kredituota € (su PVM)", f"{total_kred:,.2f}")
k3.metric("Faktas € (su PVM)", f"{total_faktas:,.2f}")
k4.metric("Likutis € (su PVM)", f"{total_like:,.2f}")

def progress_bar(p: float) -> str:
    p = 0.0 if pd.isna(p) else float(p)
    p = max(0.0, p)
    blocks = int(min(100.0, p) // 5)
    return "█" * blocks + "░" * (20 - blocks) + f"  {p:.1f}%"

# % išnaudota
den = out["SutartiesPlanas"].replace(0, np.nan)
out["PctIsnaudota"] = np.where(den.isna(), 0.0, (out["Faktas"] / den) * 100.0)
out["PctIsnaudota"] = out["PctIsnaudota"].clip(lower=0, upper=999)
out["Progresas"] = out["PctIsnaudota"].apply(progress_bar)

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

# 🎯 Filtras: Klientas -> Sutartis
st.divider()
st.subheader("🎯 Konkrečios sutarties likutis")

sel_df = out.copy()
sel_df["Klientas"] = sel_df["Klientas"].astype(str).str.strip()
sel_df["SutartiesID"] = sel_df["SutartiesID"].astype(str).str.strip()
klientai = sorted(sel_df["Klientas"].dropna().unique().tolist())
sel_client = st.selectbox("Pasirink Klientą", options=klientai, index=0 if klientai else None)

sutartys = []
if sel_client:
    sutartys = sorted(
        sel_df.loc[sel_df["Klientas"] == sel_client, "SutartiesID"].dropna().unique().tolist()
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
        pct = 0.0 if planas == 0 else floor2((faktas / planas) * 100)

        c1, c2, c3 = st.columns(3)
        c1.metric("Išrašyta € (su PVM)", f"{israsyta:,.2f}")
        c2.metric("Kredituota € (su PVM)", f"{kred:,.2f}")
        c3.metric("Faktas € (su PVM)", f"{faktas:,.2f}")

        c4, c5, c6 = st.columns(3)
        c4.metric("Planas € (su PVM)", f"{planas:,.2f}")
        c5.metric("Likutis € (su PVM)", f"{likutis:,.2f}")
        c6.metric("% išnaudota", f"{pct:,.2f}%")

        st.dataframe(one[show_cols], use_container_width=True)

        # Export only this selection
        buf_one = BytesIO()
        with pd.ExcelWriter(buf_one, engine="openpyxl") as xw:
            one.to_excel(xw, sheet_name=f"{sel_contract}", index=False)
        st.download_button(
            "⬇️ Atsisiųsti šios sutarties išklotinę (.xlsx)",
            data=buf_one.getvalue(),
            file_name=f"{sel_client}__{sel_contract}__likutis_SU_PVM.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
else:
    st.info("Pasirink **Klientą** ir **Sutartį**.")

# Eksportas – visa suvestinė
buf = BytesIO()
with pd.ExcelWriter(buf, engine="openpyxl") as xw:
    out.to_excel(xw, sheet_name="Sutarciu_likuciai_SU_PVM", index=False)
    inv.to_excel(xw, sheet_name="Saskaitos_ISRASYTA_SU_PVM", index=False)
    if crn is not None and not crn.empty:
        crn.to_excel(xw, sheet_name="Kreditines_SU_PVM", index=False)

st.download_button(
    "⬇️ Eksportuoti suvestinę (.xlsx)",
    data=buf.getvalue(),
    file_name="sutarciu_likuciai_SU_PVM.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)

