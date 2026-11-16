import os
import difflib
import streamlit as st
from dotenv import load_dotenv

from ggi_agent import GGIAgent
from llm_client import GeminiClient, MockClient
from retrievalbot import RetrievalBot

# ----------------------------
# App setup
# ----------------------------
st.set_page_config(page_title="Game Glitch Investigator", page_icon="🕵️", layout="wide")
st.title("🕵️ Game Glitch Investigator")
st.caption("A tiny agent that analyzes code, proposes a fix, and runs simple reliability checks.")

# Load environment variables from .env if present
load_dotenv()

# ----------------------------
# Helpers
# ----------------------------
SAMPLE_SNIPPETS = {
    "print_spam.py": """def greet(name):
    print("Hello", name)
    print("Welcome!")
    return True
""",
    "flaky_try_except.py": """def load_data(path):
    try:
        data = open(path).read()
    except:
        return None
    return data
""",
    "mixed_issues.py": """# TODO: replace with real implementation
def compute(x, y):
    print("computing...")
    try:
        return x / y
    except:
        return 0
""",
    "cleanish.py": """import logging

def add(a, b):
    logging.info("Adding numbers")
    return a + b
""",
    "mutable_defaults.py": '''def add_score(player, scores=[]):
    """Record a score for a player."""
    scores.append(player)
    return scores


def build_profile(name, tags={}, history=list()):
    tags[name] = len(history)
    return tags
''',
    "swallowed_errors.py": """def save_score(path, score):
    try:
        with open(path, "a") as f:
            f.write(str(score))
    except OSError: pass


def parse_guess(text):
    try:
        return int(text)
    except ValueError:
        # ignore bad input
        pass
    return None
""",
    "comparison_pitfalls.py": """def describe(guess, answer, name):
    if guess == None:
        return "no guess"
    if name is "admin":
        return "admin guess"
    if guess is 42:
        return "the answer"
    if guess != None and guess == True:
        return "weird"
    return "ok"
""",
    "network_no_timeout.py": """import requests


def fetch_leaderboard(url):
    response = requests.get(url)
    return response.json()


def submit_score(url, player, score):
    return requests.post(
        url,
        json={"player": player, "score": score},
    ).status_code
""",
    "hardcoded_secrets.py": '''"""Client for a (made up) scoreboard service."""
from __future__ import annotations

API_KEY = "sk-test-1234567890"
db_password = "hunter2"


def connect():
    return {"key": API_KEY, "password": db_password}
''',
    "debug_leftovers.py": """import pdb


def apply_bonus(score, bonus):
    pdb.set_trace()
    if bonus > 10:
        breakpoint()
    return score + bonus
""",
    "flag_only_issues.py": """# FIXME: none of these have an automatic fix; they should be flagged only.
from math import *


def read_config(path):
    f = open(path)
    return f.read()


def run_formula(expression):
    return eval(expression)


def last_index_sum(items):
    total = 0
    for i in range(len(items) + 1):
        total += items[i]
    return total


def game_loop():
    while True:
        pass
""",
}


GAME_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "game")
_SKIP_DIRS = {"__pycache__", ".git", ".pytest_cache", ".venv", "venv", "node_modules"}
_SKIP_EXTS = {".pyc", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".db", ".sqlite", ".zip"}


def list_game_files() -> list:
    """
    Walk game/ and return [(folder, [filenames])] with folder relative to game/
    ("" for the top level), folders and files sorted, top level first.
    """
    groups = []
    for root, dirs, files in os.walk(GAME_DIR):
        dirs[:] = sorted(d for d in dirs if d not in _SKIP_DIRS)
        names = sorted(f for f in files if os.path.splitext(f)[1].lower() not in _SKIP_EXTS)
        if names:
            rel = os.path.relpath(root, GAME_DIR)
            groups.append(("" if rel == "." else rel.replace("\\", "/"), names))
    return groups


def load_game_file(rel_path: str) -> None:
    """Button callback: put a game/ file's contents into the input code box."""
    try:
        with open(os.path.join(GAME_DIR, rel_path), "r", encoding="utf8") as f:
            text = f.read()
    except (OSError, UnicodeDecodeError) as e:
        st.session_state["file_error"] = f"Could not read game/{rel_path}: {e}"
        return
    st.session_state["file_error"] = None
    st.session_state["code_input"] = text
    st.session_state["loaded_file"] = rel_path
    st.session_state["loaded_text"] = text
    st.session_state["sample_choice"] = "(none)"  # the file takes over from any chosen sample


@st.cache_resource
def get_retrieval_bot() -> RetrievalBot:
    """Index the game/ files once per server process."""
    return RetrievalBot(src_folder=GAME_DIR)


def retrieve_context(glitch_description: str, top_k: int = 3) -> list:
    """Snippets from game/ most relevant to the glitch, as [(label, text)]."""
    if not glitch_description.strip() or not os.path.isdir(GAME_DIR):
        return []
    return get_retrieval_bot().retrieve(glitch_description, top_k=top_k)


def render_diff(original: str, revised: str) -> str:
    """Return a unified diff string."""
    diff_lines = difflib.unified_diff(
        original.splitlines(),
        revised.splitlines(),
        fromfile="original",
        tofile="fixed",
        lineterm="",
    )
    return "\n".join(diff_lines)


def require_code_input(code: str) -> bool:
    if not code.strip():
        st.warning("Paste some code or load a sample snippet to begin.")
        return False
    return True


# ----------------------------
# Sidebar controls
# ----------------------------
st.sidebar.header("Settings")

mode = st.sidebar.selectbox(
    "Model mode",
    [
        "Heuristic only (no API)",
        "Gemini (requires API key)",
    ],
    help="Heuristic mode runs fully offline. Gemini mode calls the Gemini API for analysis and fix proposal.",
)

# [cite_start]UPDATED: Added a warning for free-tier users to manage expectations regarding API limits. [cite: 176, 192]
if mode == "Gemini (requires API key)":
    st.sidebar.warning("⚠️ Gemini Free Tier: You have a limit of ~20 requests. Use Heuristic mode for initial testing to save your quota.")

model_name = st.sidebar.selectbox(
    "Gemini model",
    ["gemini-flash-lite-latest", "gemini-2.5-flash", "gemini-2.5-pro"],
    disabled=(mode != "Gemini (requires API key)"),
)

temperature = st.sidebar.slider(
    "Temperature",
    min_value=0.0,
    max_value=1.0,
    value=0.2,
    step=0.1,
    disabled=(mode != "Gemini (requires API key)"),
    help="Lower values tend to be more consistent. Higher values tend to be more creative.",
)

st.sidebar.divider()

sample_choice = st.sidebar.selectbox(
    "Load a sample snippet",
    ["(none)"] + list(SAMPLE_SNIPPETS.keys()),
    key="sample_choice",
)

with st.sidebar.expander("📂 Browse game/ files", expanded=False):
    game_groups = list_game_files()
    if not game_groups:
        st.caption("No files found in game/.")
    for folder, names in game_groups:
        st.caption(f"📁 game/{folder}" if folder else "📁 game/")
        for name in names:
            rel_path = f"{folder}/{name}" if folder else name
            st.button(
                name,
                key=f"game_file::{rel_path}",
                on_click=load_game_file,
                args=(rel_path,),
                use_container_width=True,
                type="primary" if st.session_state.get("loaded_file") == rel_path else "secondary",
            )
    if st.session_state.get("file_error"):
        st.error(st.session_state["file_error"])

show_debug = st.sidebar.checkbox("Show debug details", value=False)

# ----------------------------
# Choose client
# ----------------------------
client = None
client_status = ""

if mode == "Heuristic only (no API)":
    client = MockClient()
    client_status = "Using MockClient. No network calls."
else:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        client = None
        client_status = "Missing GEMINI_API_KEY. Add it to your .env file to use Gemini mode."
    else:
        client = GeminiClient(model_name=model_name, temperature=temperature)
        client_status = "Gemini client ready."

st.sidebar.info(client_status)

# ----------------------------
# Main input
# ----------------------------
col_left, col_right = st.columns([1, 1])

with col_left:
    st.subheader("Input code")
    if sample_choice != "(none)":
        default_code = SAMPLE_SNIPPETS[sample_choice]
    else:
        default_code = st.session_state.get("code_input", "")

    code_input = st.text_area(
        "Paste a Python snippet",
        value=default_code,
        height=320,
        placeholder="Paste code here...",
        label_visibility="collapsed",
    )
    st.session_state["code_input"] = code_input

    loaded_file = st.session_state.get("loaded_file")
    if loaded_file and sample_choice == "(none)":
        edited = code_input != st.session_state.get("loaded_text")
        st.caption(f"Loaded from `game/{loaded_file}`" + (" (edited)" if edited else ""))

    glitch_description = st.text_area(
        "Describe the glitch (optional)",
        height=100,
        placeholder="e.g. The score goes negative after a wrong guess, or the game crashes when I enter letters.",
        help="Tell the agent what you saw going wrong. In Gemini mode it is used to look for a cause in the code; "
        "in heuristic mode it is only recorded as a reported issue.",
        key="glitch_description",
    )

    run_button = st.button("Run Game Glitch Investigator", type="primary", use_container_width=True)

with col_right:
    st.subheader("Outputs")
    st.write("Run the workflow to see issues, a proposed fix, and a risk report.")

# ----------------------------
# Run workflow
# ----------------------------
if run_button:
    if not require_code_input(code_input):
        st.stop()

    if mode == "Gemini (requires API key)" and client is None:
        st.error("Gemini mode is selected, but no API key is available.")
        st.stop()

    agent = GGIAgent(client=client)

    context_snippets = retrieve_context(glitch_description)

    with st.spinner("Game Glitch Investigator is on the job..."):
        result = agent.run(code_input, glitch_description, context_snippets)

    issues = result.get("issues", [])
    fixed_code = result.get("fixed_code", "")
    risk = result.get("risk", {})
    logs = result.get("logs", [])

    # Layout for results
    res_left, res_right = st.columns([1, 1])

    with res_left:
        st.subheader("Detected issues")
        if not issues:
            st.success("No issues detected by the current analyzer.")
        else:
            for i, issue in enumerate(issues, start=1):
                issue_type = issue.get("type", "Issue")
                severity = issue.get("severity", "Unknown")
                msg = issue.get("msg", "").strip()

                badge = f"{issue_type} | {severity}"
                st.markdown(f"**{i}. {badge}**")
                if msg:
                    st.write(msg)

    with res_right:
        st.subheader("Risk report")
        if not risk:
            st.info("No risk report was produced.")
        else:
            score = risk.get("score", None)
            level = risk.get("level", "unknown")
            should_autofix = risk.get("should_autofix", None)
            reasons = risk.get("reasons", [])

            top_cols = st.columns(3)
            with top_cols[0]:
                st.metric("Risk level", str(level).upper())
            with top_cols[1]:
                st.metric("Score", "-" if score is None else int(score))
            with top_cols[2]:
                st.metric("Auto-fix?", "-" if should_autofix is None else ("YES" if should_autofix else "NO"))

            if reasons:
                st.write("**Reasons:**")
                for r in reasons:
                    st.write(f"- {r}")

    if glitch_description.strip():
        with st.expander(f"Retrieved context from game/ ({len(context_snippets)})"):
            if not context_snippets:
                st.info("No snippets in game/ matched the glitch description.")
            for label, text in context_snippets:
                st.markdown(f"**{label}**")
                st.code(text, language="markdown" if ".md" in label else "python")

    st.divider()

    # [cite_start]UPDATED: Check if a fallback occurred due to API limits/errors and notify the user. [cite: 119, 128]
    if any("API Error" in log.get("message", "") for log in logs):
        st.warning("⚠️ API Request Failed: Game Glitch Investigator hit a limit or network error and used heuristic rules instead.")

    st.subheader("Proposed fix")
    if not fixed_code.strip():
        st.warning("No fix was produced. This can happen if the agent refused or had parsing errors.")
    else:
        fix_cols = st.columns([1, 1])

        with fix_cols[0]:
            st.text_area("Fixed code", value=fixed_code, height=320)

        with fix_cols[1]:
            diff_text = render_diff(code_input, fixed_code)
            st.text_area("Diff (unified)", value=diff_text, height=320)

    st.divider()

    st.subheader("Agent trace")
    if not logs:
        st.info("No trace logs were produced.")
    else:
        for entry in logs:
            step = entry.get("step", "LOG")
            message = entry.get("message", "")
            st.write(f"**{step}:** {message}")

    if show_debug:
        st.divider()
        st.subheader("Debug payload")
        st.json(result)
