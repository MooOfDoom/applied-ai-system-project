# FIXME: none of these have an automatic fix; they should be flagged only.
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
