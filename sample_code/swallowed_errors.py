def save_score(path, score):
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
