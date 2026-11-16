def describe(guess, answer, name):
    if guess == None:
        return "no guess"
    if name is "admin":
        return "admin guess"
    if guess is 42:
        return "the answer"
    if guess != None and guess == True:
        return "weird"
    return "ok"
