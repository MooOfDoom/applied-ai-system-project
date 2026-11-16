import requests


def fetch_leaderboard(url):
    response = requests.get(url)
    return response.json()


def submit_score(url, player, score):
    return requests.post(
        url,
        json={"player": player, "score": score},
    ).status_code
