from logic_utils import check_guess

def test_winning_guess():
    # If the secret is 50 and guess is 50, it should be a win
    result, _ = check_guess(50, 50)
    assert result == "Win"

def test_guess_too_high():
    # If secret is 50 and guess is 60, hint should be "Too High"
    result, _ = check_guess(60, 50)
    assert result == "Too High"

def test_guess_too_low():
    # If secret is 50 and guess is 40, hint should be "Too Low"
    result, _ = check_guess(40, 50)
    assert result == "Too Low"


# --- Regression tests for the "Attempts left" counter being off by one ---
# The counter lives in app.py, so these drive the real Streamlit app.
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP_PATH = str(Path(__file__).resolve().parent.parent / "app.py")
NORMAL_LIMIT = 8


def _new_app():
    at = AppTest.from_file(APP_PATH).run()
    assert not at.exception
    return at


def _guess(at, value):
    at.text_input[0].set_value(str(value))
    at.button[0].click()  # the form's submit button
    return at.run()


def _wrong_guess(at):
    secret = at.session_state.secret
    return _guess(at, 1 if secret != 1 else 2)


def _attempts_left(at):
    text = at.info[0].value
    return int(text.rsplit("Attempts left:", 1)[1].strip())


def test_new_game_starts_with_zero_attempts_used():
    at = _new_app()
    assert at.session_state.attempts == 0
    assert _attempts_left(at) == NORMAL_LIMIT


def test_counter_decreases_on_the_first_guess():
    at = _new_app()
    _wrong_guess(at)
    assert at.session_state.attempts == 1
    assert _attempts_left(at) == NORMAL_LIMIT - 1


def test_counter_decreases_by_one_on_every_guess():
    at = _new_app()
    for used in range(1, NORMAL_LIMIT):
        _wrong_guess(at)
        assert at.session_state.attempts == used
        assert _attempts_left(at) == NORMAL_LIMIT - used


def test_one_guess_left_after_seven_guesses():
    at = _new_app()
    for _ in range(NORMAL_LIMIT - 1):
        _wrong_guess(at)
    assert _attempts_left(at) == 1
    assert at.session_state.status == "playing"


def test_game_ends_only_after_the_eighth_guess():
    at = _new_app()
    for _ in range(NORMAL_LIMIT):
        _wrong_guess(at)
    assert at.session_state.status == "lost"
    assert _attempts_left(at) == 0


def test_invalid_input_does_not_use_an_attempt():
    at = _new_app()
    _guess(at, "abc")
    assert at.session_state.attempts == 0
    assert _attempts_left(at) == NORMAL_LIMIT


def test_new_game_resets_the_counter():
    at = _new_app()
    _wrong_guess(at)
    _wrong_guess(at)
    at.button[1].click()  # New Game
    at.run()
    assert at.session_state.attempts == 0
    assert _attempts_left(at) == NORMAL_LIMIT
