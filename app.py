import random
import streamlit as st

from logic_utils import check_guess, get_range_for_difficulty, parse_guess, update_score


st.set_page_config(page_title="Glitchy Guesser", page_icon="🎮")

st.title("🎮 Game Glitch Investigator")
st.caption("An AI-generated guessing game. Something is off.")

st.sidebar.header("Settings")

difficulty = st.sidebar.selectbox(
    "Difficulty",
    ["Easy", "Normal", "Hard"],
    index=1,
)

attempt_limit_map = {
    "Easy": 6,
    "Normal": 8,
    "Hard": 5,
}
attempt_limit = attempt_limit_map[difficulty]

low, high = get_range_for_difficulty(difficulty)

st.sidebar.caption(f"Range: {low} to {high}")
st.sidebar.caption(f"Attempts allowed: {attempt_limit}")

def start_new_game():
    st.session_state.attempts = 0
    st.session_state.secret = random.randint(low, high)
    st.session_state.score = 0
    st.session_state.status = "playing"
    st.session_state.history = []


if "attempts" not in st.session_state:
    start_new_game()

# Changing difficulty changes the range, so start a fresh game.
if st.session_state.get("difficulty") != difficulty:
    st.session_state.difficulty = difficulty
    start_new_game()

st.subheader("Make a guess")

# Filled after the guess is processed so the counters are never one step stale.
state_box = st.container()

with st.form("guess_form"):
    raw_guess = st.text_input("Enter your guess:", key=f"guess_input_{difficulty}")
    submit = st.form_submit_button("Submit Guess 🚀")

new_game = st.button("New Game 🔁")
show_hint = st.checkbox("Show hint", value=True)

if new_game:
    start_new_game()
    st.rerun()

just_played = False
if submit and st.session_state.status == "playing":
    just_played = True
    ok, guess_int, err = parse_guess(raw_guess)

    if not ok:
        st.error(err)
    else:
        st.session_state.attempts += 1
        st.session_state.history.append(guess_int)

        outcome, message = check_guess(guess_int, st.session_state.secret)

        if show_hint:
            st.warning(message)

        st.session_state.score = update_score(
            current_score=st.session_state.score,
            outcome=outcome,
            attempt_number=st.session_state.attempts,
        )

        if outcome == "Win":
            st.balloons()
            st.session_state.status = "won"
            st.success(
                f"You won! The secret was {st.session_state.secret}. "
                f"Final score: {st.session_state.score}"
            )
        elif st.session_state.attempts >= attempt_limit:
            st.session_state.status = "lost"
            st.error(
                f"Out of attempts! "
                f"The secret was {st.session_state.secret}. "
                f"Score: {st.session_state.score}"
            )

with state_box:
    st.info(
        f"Guess a number between {low} and {high}. "
        f"Attempts left: {attempt_limit - st.session_state.attempts}"
    )

    with st.expander("Developer Debug Info"):
        st.write("Secret:", st.session_state.secret)
        st.write("Attempts:", st.session_state.attempts)
        st.write("Score:", st.session_state.score)
        st.write("Difficulty:", difficulty)
        st.write("History:", st.session_state.history)

if st.session_state.status != "playing" and not just_played:
    if st.session_state.status == "won":
        st.success("You already won. Start a new game to play again.")
    else:
        st.error("Game over. Start a new game to try again.")
    st.stop()

st.divider()
st.caption("Built by an AI that claims this code is production-ready.")
