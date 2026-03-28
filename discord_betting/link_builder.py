"""
Hard Rock Bet search link builder.
Generates a search URL from team names and optional sport/event info.
"""

from urllib.parse import quote


def build_hardrock_url(teams: list[str], extra: str | None = None) -> str:
    """
    Build a Hard Rock Bet search URL for the given teams.

    Args:
        teams:  List of canonical team names (max 2 used in query).
        extra:  Optional extra search term (e.g. sport name). Appended if provided.

    Returns:
        Full URL string, e.g.:
        https://www.hardrock.bet/sportsbook/search/Los%20Angeles%20Lakers%20Boston%20Celtics
    """
    parts = list(teams[:2])  # use at most 2 teams
    if extra:
        parts.append(extra)

    query = " ".join(p for p in parts if p)
    encoded = quote(query, safe="")
    return f"https://www.hardrock.bet/sportsbook/search/{encoded}"
