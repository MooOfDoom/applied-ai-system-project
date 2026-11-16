"""Client for a (made up) scoreboard service."""
from __future__ import annotations

API_KEY = "sk-test-1234567890"
db_password = "hunter2"


def connect():
    return {"key": API_KEY, "password": db_password}
