import streamlit as st
import streamlit_authenticator as stauth

st.set_page_config(page_title="Sutarčių likučių skydelis", page_icon="📁", layout="wide")

# --- Diagnozė: parodom versiją ir ar gaunam Secrets ---
st.caption(f"streamlit-authenticator version: {getattr(stauth, '__version__', 'unknown')}")

# --- Auth konfigas iš Secrets ---
try:
    auth_conf = st.secrets["auth"]
    creds_src = st.secrets["credentials"]
except Exception as e:
    st.error("Nerasta [auth] arba [credentials] sekcija Secrets'e. Patikrink App → Settings → Secrets.")
    st.stop()

users = creds_src.get("users", [])
names = creds_src.get("names", [])
passwords = creds_src.get("passwords", [])
roles = creds_src.get("roles", [])

# Greita validacija
if not (len(users) == len(names) == len(passwords) == len(roles) and len(users) > 0):
    st.error("Secrets klaida: users/names/passwords/roles masyvų ilgiai turi sutapti ir būti > 0.")
    st.write("users:", users)
    st.write("names:", names)
    st.write("roles:", roles)
    st.stop()

creds = {"usernames": {}}
for i, username in enumerate(users):
    creds["usernames"][username] = {
        "name": names[i],
        "password": passwords[i],  # BCRYPT hash
        "role": roles[i],
    }

authenticator = stauth.Authenticate(
    credentials=creds,
    cookie_name=auth_conf["cookie_name"],
    key=auth_conf["cookie_key"],
    cookie_expiry_days=auth_conf.get("cookie_expiry_days", 7),
)

# --- Prisijungimas ---
name, auth_status, username = authenticator.login("Prisijungimas")
if auth_status is False:
    st.error("Neteisingas vartotojo vardas arba slaptažodis.")
    st.stop()
elif auth_status is None:
    st.info("Įvesk prisijungimo duomenis.")
    st.stop()

# --- Prisijungus ---
with st.sidebar:
    st.markdown(f"**👤 {name} (`{username}`)**")
    authenticator.logout("Atsijungti", "sidebar")
    st.divider()

st.success(f"Sveiki, {name}! Prisijungimas sėkmingas.")
# --- ČIA toliau dedasi tavo puslapiai ir visas skydelio turinys ---
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
