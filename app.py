import streamlit as st
import bcrypt
from typing import Dict, Any

# =========================
# PUSLAPIO NUSTATYMAI + TEMA
# =========================
st.set_page_config(
    page_title="Sutarčių likučių skydelis",
    page_icon="📁",
    layout="wide",
)

# --- Tamsi neon CSS (lengvas, nekenkia Streamlit temai) ---
st.markdown("""
<style>
:root {
  --neon: #00FFC6;
  --bg: #0E1117;
  --card: #161A23;
  --text: #E6E6E6;
  --muted: #9AA4B2;
}
html, body, [class*="st-"] {
  background-color: var(--bg);
  color: var(--text);
}
div[data-testid="stSidebar"] {
  background-color: var(--card);
  border-right: 1px solid #232A36;
}
h1, h2, h3 { color: var(--neon); }
a, .stButton>button { color: var(--neon); }
.stAlert > div { background-color: #141925; border: 1px solid #263046; }
.stSuccess > div { border-color: #00FFC6; }
hr, .stDivider { border-color: #263046 !important; }
</style>
""", unsafe_allow_html=True)

# =========================
# SECRETS VALIDACIJA
# =========================
def read_secrets() -> Dict[str, Any]:
    try:
        auth_conf = st.secrets["auth"]
        creds = st.secrets["credentials"]
    except Exception:
        st.error("❌ Trūksta [auth] arba [credentials] sekcijų Secrets'e. Eik į App → Settings → Secrets.")
        st.stop()

    # Ištraukiam sąrašus
    users = creds.get("users", [])
    names = creds.get("names", [])
    passwords = creds.get("passwords", [])
    roles = creds.get("roles", [])

    # 1) visi sąrašai vienodo ilgio ir ne tušti
    if not (len(users) == len(names) == len(passwords) == len(roles) and len(users) > 0):
        st.error("❌ Secrets klaida: users/names/passwords/roles masyvų ilgiai turi sutapti ir būti > 0.")
        st.stop()

    # 2) password'ų formatas – bcrypt ($2b$...)
    if any(not str(p).startswith("$2b$") for p in passwords):
        st.error("❌ Bent vienas 'password' NĖRA bcrypt hash (turi prasidėti $2b$...).")
        st.stop()

    # Suformuojam map'ą: username -> {name, hash, role}
    usermap: Dict[str, Dict[str, str]] = {}
    for i, u in enumerate(users):
        usermap[u] = {
            "name": names[i],
            "hash": passwords[i],
            "role": roles[i],
        }

    # Auth nustatymai (čia cookie info – nenaudojame tiesiogiai, bet laikom vienoje vietoje)
    cookie_info = {
        "cookie_name": auth_conf.get("cookie_name", "sutartys_login"),
        "cookie_key": auth_conf.get("cookie_key", ""),
        "cookie_expiry_days": int(auth_conf.get("cookie_expiry_days", 7)),
    }
    if not cookie_info["cookie_key"] or len(cookie_info["cookie_key"]) < 32:
        st.warning("⚠️ Secrets [auth].cookie_key turėtų būti ilga atsitiktinė frazė (≥ 32 simbolių).")

    return {"users": usermap, "auth": cookie_info}

SECRETS = read_secrets()


# =========================
# AUTH PAGAL BCRYPT + SESIJA
# =========================
def verify(username: str, password: str) -> bool:
    user = SECRETS["users"].get(username)
    if not user:
        return False
    hashed = user["hash"]
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False

def is_logged_in() -> bool:
    return st.session_state.get("auth_user") is not None

def do_login(username: str):
    u = SECRETS["users"][username]
    st.session_state["auth_user"] = username
    st.session_state["auth_name"] = u["name"]
    st.session_state["auth_role"] = u["role"]

def logout():
    for k in ("auth_user", "auth_name", "auth_role"):
        st.session_state.pop(k, None)
    st.experimental_rerun()


# =========================
# LOGIN EKRANAS
# =========================
def login_view():
    st.markdown("<h2 style='text-align:center;'>Sutarčių likučių skydelis</h2>", unsafe_allow_html=True)
    st.markdown("<p style='text-align:center;color:#9AA4B2;'>Prisijunk, kad tęstum</p>", unsafe_allow_html=True)

    with st.form("login", clear_on_submit=False):
        username = st.text_input("Vartotojo vardas")
        password = st.text_input("Slaptažodis", type="password")
        submit = st.form_submit_button("Prisijungti")

    if submit:
        if not username or not password:
            st.error("Įvesk vartotojo vardą ir slaptažodį.")
            st.stop()
        if verify(username, password):
            do_login(username)
            st.success("Prisijungta. Kraunama...")
            st.experimental_rerun()
        else:
            st.error("Neteisingas vartotojo vardas arba slaptažodis.")
            st.stop()

    # Sustabdom, kad nepraslystų žemiau
    st.stop()


# =========================
# PUSLAPIŲ LOGIKA
# =========================
def page_likuciai():
    st.subheader("📊 Likučiai")
    st.caption("Čia patalpink savo esamas lenteles, filtrus, vizualizacijas.")
    # TODO: tavo likučių logika
    st.info("Pavyzdinis blokas. Įdėk savo skaičiavimus ir grafikus.")

def page_ikelimas():
    st.subheader("📤 Įkėlimas")
    st.caption("Failų įkėlimas / atnaujinimas.")
    uploaded = st.file_uploader("Įkelk Excel (*.xlsx)", type=["xlsx"])
    if uploaded:
        st.success(f"Failas gautas: {uploaded.name}")
        # TODO: tavo parsingo ir įrašymo logika
        st.info("Čia apdorok įkeltą failą.")

def page_nustatymai():
    st.subheader("⚙️ Nustatymai")
    st.caption("Vartotojo nustatymai.")
    st.write("Vartotojas:", st.session_state.get("auth_user"))
    st.write("Vardas:", st.session_state.get("auth_name"))
    st.write("Rolė:", st.session_state.get("auth_role"))

def page_admin():
    st.subheader("🛡️ Admin")
    if st.session_state.get("auth_role") != "admin":
        st.warning("Neturi teisės pasiekti „Admin“ puslapio.")
        return
    st.success("Sveika, administratore!")
    # TODO: čia daryk admin funkcijas (pvz., konfigūracijų peržiūra, ataskaitų ribojimai ir pan.)
    st.info("Pavyzdinis admin blokas.")


# =========================
# VYKDYMAS
# =========================
if not is_logged_in():
    login_view()

# Prisijungus – šoninis meniu + logout
with st.sidebar:
    st.markdown(f"**👤 {st.session_state['auth_name']} (`{st.session_state['auth_user']}`)**")
    if st.button("Atsijungti"):
        logout()
    st.divider()
    page = st.radio("Puslapiai", ["Likučiai", "Įkėlimas", "Nustatymai", "Admin"], index=0)

# Puslapių routing'as
if page == "Likučiai":
    page_likuciai()
elif page == "Įkėlimas":
    page_ikelimas()
elif page == "Nustatymai":
    page_nustatymai()
elif page == "Admin":
    page_admin()
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
