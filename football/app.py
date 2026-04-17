from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from football.mcp_client import (
    MCPClient,
    MCPError,
    extract_corners,
    extract_fulltime,
    extract_halftime,
    extract_next_goal,
)

app = FastAPI(title="FootballBin Predictions")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

_mcp: MCPClient | None = None

LEAGUES = [
    {"id": "premier_league", "label": "Premier League"},
    {"id": "champions_league", "label": "Champions League"},
    {"id": "la_liga", "label": "La Liga"},
    {"id": "bundesliga", "label": "Bundesliga"},
    {"id": "serie_a", "label": "Serie A"},
    {"id": "ligue_1", "label": "Ligue 1"},
]

TEAM_ALIASES = [
    "Arsenal", "Aston Villa", "Bournemouth", "Brentford", "Brighton",
    "Chelsea", "Crystal Palace", "Everton", "Fulham", "Ipswich",
    "Leicester", "Liverpool", "Man City", "Man Utd", "Newcastle",
    "Nottm Forest", "Southampton", "Spurs", "West Ham", "Wolves",
    "Barcelona", "Real Madrid", "Bayern Munich", "PSG", "Juventus",
    "Inter Milan", "Dortmund", "Atletico Madrid", "Porto", "Ajax",
]


@app.on_event("startup")
async def startup():
    global _mcp
    _mcp = MCPClient()


@app.on_event("shutdown")
async def shutdown():
    if _mcp:
        await _mcp.close()


@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")


@app.get("/api/leagues")
async def get_leagues():
    return {"leagues": LEAGUES, "teams": TEAM_ALIASES}


@app.get("/api/predictions")
async def get_predictions(
    league: str,
    matchweek: int | None = None,
    home_team: str | None = None,
    away_team: str | None = None,
):
    try:
        raw = await _mcp.get_predictions(
            league=league,
            matchweek=matchweek,
            home_team=home_team or None,
            away_team=away_team or None,
        )
    except MCPError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=502)
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"Request failed: {e}"}, status_code=502)

    for match in raw.get("matches", []):
        preds = match.get("predictions", [])
        match["score_halftime"] = extract_halftime(preds)
        match["score_fulltime"] = extract_fulltime(preds)
        match["corners"] = extract_corners(preds)
        match["next_goal"] = extract_next_goal(preds)

    return {"ok": True, "data": raw}


if __name__ == "__main__":
    uvicorn.run("football.app:app", host="0.0.0.0", port=8001, reload=True)
