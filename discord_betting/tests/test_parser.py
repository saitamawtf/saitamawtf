"""
Unit tests for BetParser.
Run with: pytest tests/ -v   (from discord_betting/ directory)
"""

import sys
import os

# Allow imports from parent directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from parser.bet_parser import BetParser, BetResult

parser = BetParser()


# ─── Helpers ─────────────────────────────────────────────────────────────────

def parse(text: str) -> BetResult:
    result = parser.parse(text)
    assert result is not None, f"Expected a parse result for: {text!r}"
    return result


# ─── Spread bets ─────────────────────────────────────────────────────────────

class TestSpread:
    def test_lakers_minus_spread_with_odds(self):
        bet = parse("Lakers -3.5 (-110)")
        assert bet.bet_type == "spread"
        assert bet.line == -3.5
        assert bet.odds == -110
        assert "Los Angeles Lakers" in bet.teams

    def test_chiefs_minus_7(self):
        bet = parse("Chiefs -7 (-115)")
        assert bet.bet_type == "spread"
        assert bet.line == -7.0
        assert bet.odds == -115
        assert "Kansas City Chiefs" in bet.teams

    def test_gsw_plus_spread(self):
        bet = parse("GSW +5.5 (-105)")
        assert bet.bet_type == "spread"
        assert bet.line == +5.5
        assert bet.odds == -105
        assert "Golden State Warriors" in bet.teams

    def test_yankees_runline_plus(self):
        bet = parse("NYY -1.5 (+140)")
        assert bet.bet_type == "spread"
        assert bet.line == -1.5
        assert bet.odds == +140
        assert "New York Yankees" in bet.teams

    def test_lal_short_abbrev(self):
        bet = parse("LAL -3 (-110)")
        assert bet.bet_type == "spread"
        assert bet.line == -3.0
        assert "Los Angeles Lakers" in bet.teams

    def test_phx_minus_4(self):
        bet = parse("PHX -4 (-110)")
        assert bet.bet_type == "spread"
        assert bet.line == -4.0
        assert "Phoenix Suns" in bet.teams

    def test_ne_patriots_spread(self):
        bet = parse("NE +3.5 (-108)")
        assert bet.bet_type == "spread"
        assert bet.line == +3.5
        assert "New England Patriots" in bet.teams

    def test_buf_bills_minus(self):
        bet = parse("BUF -6.5 (-115)")
        assert bet.bet_type == "spread"
        assert bet.line == -6.5
        assert "Buffalo Bills" in bet.teams


# ─── Over/Under bets ─────────────────────────────────────────────────────────

class TestOverUnder:
    def test_over_with_teams_and_no_odds(self):
        bet = parse("Over 220.5 MIA vs BOS")
        assert bet.bet_type == "over_under"
        assert bet.line == 220.5
        assert "Miami Heat" in bet.teams
        assert "Boston Celtics" in bet.teams

    def test_under_with_teams_and_odds(self):
        bet = parse("Under 45.5 NE vs KC (-108)")
        assert bet.bet_type == "over_under"
        assert bet.line == 45.5
        assert bet.odds == -108
        assert "New England Patriots" in bet.teams
        assert "Kansas City Chiefs" in bet.teams

    def test_over_mlb_teams(self):
        bet = parse("Over 7.5 NYY vs BOS (-115)")
        assert bet.bet_type == "over_under"
        assert bet.line == 7.5
        assert bet.odds == -115
        # NYY = Yankees; BOS in context of MLB = Red Sox vs NBA = Celtics
        # Both valid, just check line and odds
        assert bet.line == 7.5

    def test_under_nba_total(self):
        bet = parse("Under 215 DAL vs PHX")
        assert bet.bet_type == "over_under"
        assert bet.line == 215.0
        assert "Dallas Mavericks" in bet.teams

    def test_short_o_abbreviation(self):
        bet = parse("O 220 LAL vs MIA")
        assert bet.bet_type == "over_under"
        assert bet.line == 220.0

    def test_short_u_abbreviation(self):
        bet = parse("U 48.5 KC vs BUF")
        assert bet.bet_type == "over_under"
        assert bet.line == 48.5


# ─── Moneyline bets ──────────────────────────────────────────────────────────

class TestMoneyline:
    def test_yankees_moneyline_plus(self):
        bet = parse("Moneyline Yankees +150")
        assert bet.bet_type == "moneyline"
        assert bet.odds == +150
        assert "New York Yankees" in bet.teams

    def test_ml_abbreviation_celtics_minus(self):
        bet = parse("ML Boston Celtics -200")
        assert bet.bet_type == "moneyline"
        assert bet.odds == -200
        assert "Boston Celtics" in bet.teams

    def test_ml_lal_short(self):
        bet = parse("ML LAL +130")
        assert bet.bet_type == "moneyline"
        assert bet.odds == +130
        assert "Los Angeles Lakers" in bet.teams

    def test_ml_chiefs_favorite(self):
        bet = parse("Moneyline Chiefs -250")
        assert bet.bet_type == "moneyline"
        assert bet.odds == -250
        assert "Kansas City Chiefs" in bet.teams


# ─── Parlay bets ─────────────────────────────────────────────────────────────

class TestParlay:
    def test_two_leg_slash_parlay(self):
        bet = parse("LAL -3 (-110) / Chiefs -7 (-115)")
        assert bet.bet_type == "parlay"
        assert bet.is_parlay is True
        assert len(bet.legs) == 2
        assert bet.legs[0].bet_type == "spread"
        assert bet.legs[1].bet_type == "spread"

    def test_three_leg_newline_parlay(self):
        text = "ML Boston Celtics -200\nNYY -1.5 (+140)\nOver 220.5 MIA vs BOS"
        bet = parse(text)
        assert bet.bet_type == "parlay"
        assert len(bet.legs) == 3
        types = {leg.bet_type for leg in bet.legs}
        assert "moneyline" in types
        assert "spread" in types
        assert "over_under" in types

    def test_parlay_teams_aggregated(self):
        bet = parse("GSW +5.5 (-105) / ML Yankees +150")
        assert bet.is_parlay is True
        all_teams = set(bet.teams)
        assert "Golden State Warriors" in all_teams
        assert "New York Yankees" in all_teams


# ─── Invalid / edge cases ─────────────────────────────────────────────────────

class TestEdgeCases:
    def test_random_text_returns_none(self):
        assert parser.parse("invalid text abc xyz") is None

    def test_empty_string_returns_none(self):
        assert parser.parse("") is None

    def test_just_whitespace_returns_none(self):
        assert parser.parse("   \n  ") is None

    def test_number_only_returns_none(self):
        assert parser.parse("12345") is None


# ─── Sport detection ─────────────────────────────────────────────────────────

class TestSportDetection:
    def test_nba_sport_detected(self):
        bet = parse("Lakers -3.5 (-110)")
        assert bet.sport == "NBA"

    def test_nfl_sport_detected(self):
        bet = parse("Chiefs -7 (-115)")
        assert bet.sport == "NFL"

    def test_mlb_sport_detected(self):
        bet = parse("Moneyline Yankees +150")
        assert bet.sport == "MLB"

    def test_nhl_sport_detected(self):
        bet = parse("ML VGK -150")
        assert bet.sport == "NHL"
