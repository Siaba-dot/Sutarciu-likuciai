import streamlit as st
import streamlit_authenticator as stauth

# --- Puslapio nustatymai ---
st.set_page_config(page_title="Sutarčių likučių skydelis", page_icon="📁", layout="wide")

# --- Auth konfigūracija iš Secrets ---
auth_conf = st.secrets["auth"]
creds = {"usernames": {}}

# Užpildom vartotojų duomenis iš Secrets
for i, username in enumerate(st.secrets["credentials"]["users"]):
    creds["usernames"][username] = {
        "name": st.secrets["credentials"]["names"][i],
        "password": st.secrets["credentials"]["passwords"][i],  # čia BCRYPT HASH
        "role": st.secrets["credentials"]["roles"][i],
    }

# Sukuriam autentifikatorių
authenticator = stauth.Authenticate(
    credentials=creds,
    cookie_name=auth_conf["cookie_name"],
    key=auth_conf["cookie_key"],
    cookie_expiry_days=auth_conf.get("cookie_expiry_days", 7),
)

# --- Prisijungimo forma ---
name, auth_status, username = authenticator.login("Prisijungimas", location="main")

if auth_status is False:
    st.error("Neteisingas vartotojo vardas arba slaptažodis.")
    st.stop()

elif auth_status is None:
    st.info("Įvesk prisijungimo duomenis.")
    st.stop()

# ---- Jei prisijungta ----
with st.sidebar:
    st.markdown(f"**👤 {name} ({username})**")
    authenticator.logout("Atsijungti", "sidebar")
    st.write("---")

st.success(f"Sveiki, {name}!")

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
