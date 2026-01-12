import streamlit as st
from helpers_webapp import BUILD_TAG, ENVIRONMENT, init_app, set_styling
from PIL import Image

CHANGELOG_LINES_TO_SKIP = 3
DISPLAY_LATEST = 1

# Layout
set_styling()
init_app()

with st.sidebar:
    st.image(Image.open("./src/webapp/img/ALG_RGB_Robothuis.png"))

st.write("# Over Ally")

FAISS_VERSION = st.session_state["faiss_version"]


st.write(
    """Ally is door DCC en de Klantenservice ontwikkeld om medewerkers van de Klantenservice te helpen \
       met het zoeken naar informatie in hun kennisbank. Hieronder kan je de release notes bekijken."""
)

# Write changelog


@st.cache_data
def show_changelog():
    """Display changelog from ChangeLog.md file."""
    with open("changelog.md", "r", encoding="utf-8") as f:
        lines = f.readlines()[CHANGELOG_LINES_TO_SKIP:]
    version_numbers = [line for line in lines if line.startswith("### [")]
    version_idx = lines.index(version_numbers[DISPLAY_LATEST])
    st.header("Release Notes huidige versie")
    st.markdown("".join(lines[:version_idx]))
    with st.expander("Vorige Releases"):
        st.markdown("".join(lines[version_idx:]))


show_changelog()

st.markdown(f"Omgeving: '{ENVIRONMENT}', Docker-build-tag: '{BUILD_TAG}'")
st.markdown(f"De versie van de kennisbank is: `{FAISS_VERSION}`")

# Guard rails

st.session_state["feedback_key"] = None
