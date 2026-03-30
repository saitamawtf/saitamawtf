import httpx

MCP_ENDPOINT = "https://ru7m5svay1.execute-api.eu-central-1.amazonaws.com/prod/mcp"


class MCPError(Exception):
    pass


class MCPClient:
    def __init__(self):
        self._client = httpx.AsyncClient(timeout=30.0)

    async def get_predictions(
        self,
        league: str,
        matchweek: int | None = None,
        home_team: str | None = None,
        away_team: str | None = None,
    ) -> dict:
        arguments: dict = {"league": league}
        if matchweek is not None:
            arguments["matchweek"] = matchweek
        if home_team:
            arguments["home_team"] = home_team
        if away_team:
            arguments["away_team"] = away_team

        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "get_match_predictions",
                "arguments": arguments,
            },
        }

        response = await self._client.post(MCP_ENDPOINT, json=payload)
        response.raise_for_status()
        data = response.json()

        if "error" in data:
            raise MCPError(data["error"].get("message", "Unknown JSON-RPC error"))

        result = data.get("result", {})
        if result.get("isError"):
            content = result.get("content", [])
            msg = content[0].get("text", "Unknown error") if content else "Unknown error"
            raise MCPError(msg)

        structured = result.get("structuredContent")
        if structured is None:
            # Fall back to parsing text content
            content = result.get("content", [])
            if content:
                raise MCPError(content[0].get("text", "No structured content returned"))
            raise MCPError("No structured content returned")

        return structured

    async def list_tools(self) -> list:
        payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        response = await self._client.post(MCP_ENDPOINT, json=payload)
        response.raise_for_status()
        data = response.json()
        return data.get("result", {}).get("tools", [])

    async def close(self):
        await self._client.aclose()


# ── Prediction field extractors ────────────────────────────────────────────────

def _find(predictions: list[dict], keyword: str) -> str | None:
    keyword = keyword.lower()
    for p in predictions:
        if keyword in p.get("type", "").lower():
            return p.get("value")
    return None


def extract_halftime(predictions: list[dict]) -> str | None:
    return _find(predictions, "half-time") or _find(predictions, "halftime") or _find(predictions, "ht")


def extract_fulltime(predictions: list[dict]) -> str | None:
    return _find(predictions, "full-time") or _find(predictions, "fulltime") or _find(predictions, "ft score")


def extract_corners(predictions: list[dict]) -> str | None:
    return _find(predictions, "corner")


def extract_next_goal(predictions: list[dict]) -> str | None:
    return _find(predictions, "next goal")
