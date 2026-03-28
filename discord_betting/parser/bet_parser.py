"""
Bet parser: converts raw Discord message text into structured BetResult objects.

Supported formats:
  Spread:      "Lakers -3.5 (-110)"
               "Chiefs -7 (-115)"
               "GSW +5.5 (-105)"
  Over/Under:  "Over 220.5 MIA vs BOS"
               "Under 45.5 NE vs KC (-108)"
               "O 7.5 NYY vs BOS (-115)"
  Moneyline:   "Moneyline Yankees +150"
               "ML Boston Celtics -200"
               "ML LAL +130"
  Parlay:      Multiple legs separated by newlines or " / "
               "LAL -3 (-110) / MIA O220 (-115)"
"""

import re
import logging
from dataclasses import dataclass, field

from .team_aliases import resolve_team

logger = logging.getLogger(__name__)

# ─── Patterns ────────────────────────────────────────────────────────────────

# Spread: "Team Name +/-line (odds)"  e.g.  "Lakers -3.5 (-110)"
_SPREAD_RE = re.compile(
    r"^(?P<team>[A-Za-z][A-Za-z0-9\.\s\-\']*?)\s+"
    r"(?P<line>[+-]\d+\.?\d*)\s*"
    r"(?:\((?P<odds>[+-]\d+)\))?$",
    re.IGNORECASE,
)

# Over/Under: "(Over|Under|O|U) total [Team1 vs Team2] [(odds)]"
_OU_RE = re.compile(
    r"^(?P<side>Over|Under|O|U)\s+"
    r"(?P<total>\d+\.?\d*)"
    r"(?:\s+(?P<teams>.+?))?"
    r"(?:\s+\((?P<odds>[+-]\d+)\))?$",
    re.IGNORECASE,
)

# Moneyline: "(Moneyline|ML) Team +/-odds"
_ML_RE = re.compile(
    r"^(?:Moneyline|ML)\s+"
    r"(?P<team>[A-Za-z][A-Za-z0-9\.\s\-\']+?)\s+"
    r"(?P<odds>[+-]\d+)$",
    re.IGNORECASE,
)

# Team separator in over/under lines: "MIA vs BOS", "MIA v BOS", "MIA @ BOS"
_TEAM_SEP_RE = re.compile(r"\s+(?:vs?\.?|@)\s+", re.IGNORECASE)

# Leg separator in parlays
_LEG_SEP_RE = re.compile(r"\s*/\s*|\n")


# ─── Data model ──────────────────────────────────────────────────────────────

@dataclass
class LegResult:
    raw: str
    bet_type: str        # "spread" | "moneyline" | "over_under"
    teams: list[str]
    sport: str | None
    line: float | None
    odds: int | None
    confidence: float


@dataclass
class BetResult:
    raw: str
    bet_type: str        # "spread" | "moneyline" | "over_under" | "parlay"
    teams: list[str]
    sport: str | None
    line: float | None
    odds: int | None
    confidence: float
    is_parlay: bool = False
    legs: list[LegResult] = field(default_factory=list)


# ─── Parser ──────────────────────────────────────────────────────────────────

class BetParser:
    """Parse a raw bet message into a BetResult."""

    def parse(self, text: str) -> BetResult | None:
        """
        Parse *text* and return a BetResult, or None if no bet structure found.
        Tries parlay detection first (multiple legs), then single-bet patterns.
        """
        text = text.strip()
        if not text:
            return None

        # Try parlay: 2+ legs separated by "/" or newlines
        legs_raw = [s.strip() for s in _LEG_SEP_RE.split(text) if s.strip()]
        if len(legs_raw) >= 2:
            legs = [self._parse_single(leg) for leg in legs_raw]
            valid_legs = [l for l in legs if l is not None]
            if len(valid_legs) >= 2:
                all_teams: list[str] = []
                for leg in valid_legs:
                    all_teams.extend(leg.teams)
                sport = valid_legs[0].sport if valid_legs else None
                confidence = round(
                    sum(l.confidence for l in valid_legs) / len(valid_legs), 2
                )
                return BetResult(
                    raw=text,
                    bet_type="parlay",
                    teams=list(dict.fromkeys(all_teams)),  # deduplicate, keep order
                    sport=sport,
                    line=None,
                    odds=None,
                    confidence=confidence,
                    is_parlay=True,
                    legs=valid_legs,
                )

        # Single bet
        result = self._parse_single(text)
        if result is None:
            return None

        return BetResult(
            raw=result.raw,
            bet_type=result.bet_type,
            teams=result.teams,
            sport=result.sport,
            line=result.line,
            odds=result.odds,
            confidence=result.confidence,
            is_parlay=False,
            legs=[],
        )

    # ── Private helpers ───────────────────────────────────────────────────────

    def _parse_single(self, text: str) -> LegResult | None:
        """Try all single-bet patterns; return the first match or None."""
        text = text.strip()
        for parser in (self._try_moneyline, self._try_over_under, self._try_spread):
            result = parser(text)
            if result is not None:
                return result
        logger.debug("No pattern matched for: %r", text)
        return None

    def _try_spread(self, text: str) -> LegResult | None:
        m = _SPREAD_RE.match(text)
        if not m:
            return None

        team_raw = m.group("team").strip()
        line = float(m.group("line"))
        odds_str = m.group("odds")
        odds = int(odds_str) if odds_str else None

        canonical, sport, conf = resolve_team(team_raw)
        if conf == 0.0:
            return None  # Could not identify any team → likely not a real bet

        return LegResult(
            raw=text,
            bet_type="spread",
            teams=[canonical],
            sport=sport,
            line=line,
            odds=odds,
            confidence=conf,
        )

    def _try_over_under(self, text: str) -> LegResult | None:
        m = _OU_RE.match(text)
        if not m:
            return None

        total = float(m.group("total"))
        side = m.group("side").capitalize()
        side = "Over" if side.lower() in ("over", "o") else "Under"
        odds_str = m.group("odds")
        odds = int(odds_str) if odds_str else None

        teams_raw = m.group("teams") or ""
        teams: list[str] = []
        sport: str | None = None
        confidence = 0.9  # high base: total was clearly numeric

        if teams_raw:
            parts = _TEAM_SEP_RE.split(teams_raw.strip())
            for part in parts:
                part = part.strip()
                if part:
                    canonical, sp, conf = resolve_team(part)
                    teams.append(canonical)
                    if sp != "Unknown":
                        sport = sp
                    confidence = min(confidence, conf) if conf > 0 else confidence

        return LegResult(
            raw=text,
            bet_type="over_under",
            teams=teams,
            sport=sport,
            line=total,
            odds=odds,
            confidence=confidence,
        )

    def _try_moneyline(self, text: str) -> LegResult | None:
        m = _ML_RE.match(text)
        if not m:
            return None

        team_raw = m.group("team").strip()
        odds = int(m.group("odds"))

        canonical, sport, conf = resolve_team(team_raw)

        return LegResult(
            raw=text,
            bet_type="moneyline",
            teams=[canonical],
            sport=sport,
            line=None,
            odds=odds,
            confidence=conf if conf > 0 else 0.5,
        )
