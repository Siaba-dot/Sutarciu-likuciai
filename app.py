import streamlit as st

st.set_page_config(
    page_title="Sutarčių likučių skydelis",
    page_icon="💼",
    layout="wide",
    initial_sidebar_state="expanded"
)

with open("assets/neon.css", "r", encoding="utf-8") as f:
    st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

st.title("💼 Sutarčių likučių skydelis")
st.caption("Be PVM, 2 skaičiai po kablelio (nukirpimas), kreditinės su „−“.")

st.markdown(
    """
**Skyriai kairėje:**
1. 📥 **Įkėlimas** – įkelk *Sąskaitos.xlsx* ir *Kreditines.xlsx* (tavo stulpelių struktūra).
2. 🧾 **Likučiai ir planai** – ranka įvesk *Sutarties planą* ir gauk *Likutį*.
3. 📈 **MoM / WoW kiekiai** – dokumentų kiekio dinamika per mėnesius/savaites (su slankiu vidurkiu).
"""
)
