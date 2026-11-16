def add_score(player, scores=[]):
    """Record a score for a player."""
    scores.append(player)
    return scores


def build_profile(name, tags={}, history=list()):
    tags[name] = len(history)
    return tags
