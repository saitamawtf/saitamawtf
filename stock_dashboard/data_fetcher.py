"""Módulo para obtener datos de precio, analistas y noticias desde yfinance y RSS."""

import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
import yfinance as yf

logger = logging.getLogger(__name__)

TICKERS = ["META", "NVDA"]

NEWS_FEEDS: dict[str, list[str]] = {
    "META": [
        "https://feeds.finance.yahoo.com/rss/2.0/headline?s=META&region=US&lang=en-US",
        "https://news.google.com/rss/search?q=Meta+Platforms+stock+earnings&hl=en-US&gl=US&ceid=US:en",
    ],
    "NVDA": [
        "https://feeds.finance.yahoo.com/rss/2.0/headline?s=NVDA&region=US&lang=en-US",
        "https://news.google.com/rss/search?q=Nvidia+NVDA+stock+AI+chips&hl=en-US&gl=US&ceid=US:en",
    ],
}

CONSENSUS_DISPLAY: dict[str, str] = {
    "STRONG_BUY": "STRONG BUY",
    "BUY": "BUY",
    "HOLD": "HOLD",
    "UNDERPERFORM": "UNDERPERFORM",
    "SELL": "SELL",
    "N/A": "N/A",
}


def _fmt_number(n: Any) -> Optional[float]:
    try:
        return float(n) if n is not None else None
    except (TypeError, ValueError):
        return None


def fetch_price_data(ticker: str) -> dict[str, Any]:
    """Obtiene precio actual, cambio diario y datos históricos para el gráfico sparkline."""
    stock = yf.Ticker(ticker)
    info = stock.info

    current = _fmt_number(info.get("currentPrice") or info.get("regularMarketPrice")) or 0.0
    prev = _fmt_number(info.get("previousClose") or info.get("regularMarketPreviousClose")) or current
    change_abs = current - prev
    change_pct = (change_abs / prev * 100) if prev else 0.0

    hist = stock.history(period="30d", interval="1d")
    sparkline: list[dict[str, Any]] = []
    if not hist.empty:
        sparkline = [
            {"date": str(idx.date()), "close": round(float(row["Close"]), 2)}
            for idx, row in hist.iterrows()
        ]

    return {
        "ticker": ticker,
        "name": info.get("shortName", ticker),
        "price": round(current, 2),
        "change_pct": round(change_pct, 2),
        "change_abs": round(change_abs, 2),
        "volume": info.get("volume"),
        "avg_volume": info.get("averageVolume"),
        "market_cap": info.get("marketCap"),
        "week52_high": _fmt_number(info.get("fiftyTwoWeekHigh")),
        "week52_low": _fmt_number(info.get("fiftyTwoWeekLow")),
        "pe_ratio": _fmt_number(info.get("trailingPE")),
        "forward_pe": _fmt_number(info.get("forwardPE")),
        "dividend_yield": _fmt_number(info.get("dividendYield")),
        "beta": _fmt_number(info.get("beta")),
        "sparkline": sparkline,
    }


def fetch_analyst_data(ticker: str) -> dict[str, Any]:
    """Obtiene consenso de analistas y objetivos de precio."""
    stock = yf.Ticker(ticker)
    info = stock.info

    raw_consensus = (info.get("recommendationKey") or "N/A").upper()
    consensus = CONSENSUS_DISPLAY.get(raw_consensus, raw_consensus.replace("_", " "))

    return {
        "consensus": consensus,
        "mean_rating": _fmt_number(info.get("recommendationMean")),
        "num_analysts": info.get("numberOfAnalystOpinions") or 0,
        "target_mean": _fmt_number(info.get("targetMeanPrice")),
        "target_high": _fmt_number(info.get("targetHighPrice")),
        "target_low": _fmt_number(info.get("targetLowPrice")),
    }


_ATOM_NS = "{http://www.w3.org/2005/Atom}"


def _find_first(entry: ET.Element, *tags: str) -> Optional[ET.Element]:
    """Devuelve el primer elemento encontrado entre los tags dados (compara con None explícitamente)."""
    for tag in tags:
        found = entry.find(tag)
        if found is not None:
            return found
    return None


def _parse_rss(xml_text: str, limit: int = 8) -> list[dict[str, str]]:
    """Parsea un feed RSS 2.0 o Atom usando ElementTree."""
    items: list[dict[str, str]] = []
    try:
        root = ET.fromstring(xml_text)
        channel_items = root.findall(".//item")
        if not channel_items:
            channel_items = root.findall(f".//{_ATOM_NS}entry")

        for entry in channel_items[:limit]:
            title_el = _find_first(entry, "title", f"{_ATOM_NS}title")
            link_el = _find_first(entry, "link", f"{_ATOM_NS}link")
            pub_el = _find_first(entry, "pubDate", f"{_ATOM_NS}published", f"{_ATOM_NS}updated")
            desc_el = _find_first(entry, "description", f"{_ATOM_NS}summary")
            source_el = _find_first(entry, "source", f"{_ATOM_NS}source")

            title = (title_el.text or "").strip() if title_el is not None else ""
            if not title:
                continue

            link = ""
            if link_el is not None:
                link = (link_el.text or link_el.get("href") or "").strip()

            published = (pub_el.text or "").strip() if pub_el is not None else ""
            summary = (desc_el.text or "")[:280].strip() if desc_el is not None else ""
            source = ""
            if source_el is not None:
                source = (source_el.text or source_el.get("url") or "").strip()

            items.append({
                "title": title,
                "summary": summary,
                "published": published,
                "link": link,
                "source": source,
            })
    except ET.ParseError as exc:
        logger.warning("Error parseando RSS: %s", exc)
    return items


def fetch_news(ticker: str, limit: int = 8) -> list[dict[str, str]]:
    """Obtiene titulares recientes desde feeds RSS y yfinance."""
    articles: list[dict[str, str]] = []
    headers = {"User-Agent": "Mozilla/5.0 (StockInsightsDashboard/1.0)"}

    for feed_url in NEWS_FEEDS.get(ticker, []):
        try:
            with httpx.Client(timeout=10.0, follow_redirects=True, headers=headers) as client:
                resp = client.get(feed_url)
                if resp.status_code == 200:
                    articles.extend(_parse_rss(resp.text, limit))
        except Exception as exc:
            logger.warning("Error obteniendo feed %s para %s: %s", feed_url, ticker, exc)

    # Complementar con noticias de yfinance
    try:
        stock = yf.Ticker(ticker)
        yf_news = stock.news or []
        for item in yf_news[:6]:
            title = item.get("title", "").strip()
            if not title:
                # Formato nuevo de yfinance con campo 'content'
                content = item.get("content", {})
                title = content.get("title", "").strip() if isinstance(content, dict) else ""
            if not title:
                continue
            link = item.get("link") or item.get("url", "")
            published = ""
            if ts := item.get("providerPublishTime"):
                published = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%d %b %Y %H:%M UTC")
            articles.append({
                "title": title,
                "summary": (item.get("summary") or "")[:280].strip(),
                "published": published,
                "link": link,
                "source": item.get("publisher", ""),
            })
    except Exception as exc:
        logger.warning("Error obteniendo noticias yfinance para %s: %s", ticker, exc)

    # Deduplicar por título
    seen: set[str] = set()
    unique: list[dict[str, str]] = []
    for a in articles:
        if a["title"] and a["title"] not in seen:
            seen.add(a["title"])
            unique.append(a)

    return unique[:limit]


def fetch_all() -> dict[str, Any]:
    """Obtiene todos los datos de mercado para META y NVDA."""
    stocks: dict[str, Any] = {}
    for ticker in TICKERS:
        logger.info("Obteniendo datos de mercado para %s...", ticker)
        try:
            stocks[ticker] = {
                "price": fetch_price_data(ticker),
                "analyst": fetch_analyst_data(ticker),
                "news": fetch_news(ticker),
            }
        except Exception as exc:
            logger.error("Error obteniendo datos de %s: %s", ticker, exc, exc_info=True)
            stocks[ticker] = {
                "price": {"ticker": ticker, "name": ticker, "price": 0, "change_pct": 0,
                           "change_abs": 0, "sparkline": []},
                "analyst": {"consensus": "N/A", "num_analysts": 0},
                "news": [],
                "error": str(exc),
            }

    return {
        "stocks": stocks,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
