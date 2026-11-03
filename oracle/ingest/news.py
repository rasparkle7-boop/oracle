"""News / injury / tactical research from public RSS feeds.

Primary injury truth comes from structured availability data (FotMob). News is
used to surface manager changes, doubts, suspensions and narrative context.
Every claim returned here links back to its source.
"""
from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from .. import db
from ..config import settings
from .http import fetch_text, make_client

GOOGLE = "https://news.google.com/rss/search"
ESPN = "https://site.api.espn.com/apis/site/v2/sports/soccer/{league}/news"

INJURY_WORDS = (
    "injur", "ruled out", "out for", "sidelined", "hamstring", "knee", "ankle", "calf",
    "groin", "shoulder", "fitness", "doubt", "surgery", "scan", "knock", "illness", "ill ",
    "muscle", "concussion", "fracture", "torn", "strain", "back problem", "hip", "thigh",
)
SUSPENSION_WORDS = ("suspens", "red card", "banned", "ban ", "booked", "accumulated")
MANAGER_WORDS = ("manager", "head coach", "coach", "sacked", "appoint", "interim", "resign", "departure")
LINEUP_WORDS = ("line-up", "lineup", "starting xi", "team news", "rotation", "rested", "make changes")
TACTICAL_WORDS = ("tactic", "formation", "system", "press", "counter", "wing-back", "back three", "midfield")
WEATHER_WORDS = ("rain", "weather", "wind", "pitch", "dew", "heat", "storm", "conditions")

STOP = {"the", "a", "an", "and", "or", "for", "with", "from", "this", "that", "his", "her",
        "their", "after", "before", "ahead", "could", "would", "will", "has", "have", "was",
        "were", "is", "are", "be", "been", "in", "on", "at", "to", "of", "as", "by", "it"}


def _clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = re.sub(r"&[a-z]+;", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def classify(text: str) -> list[str]:
    low = (text or "").lower()
    tags = []
    if any(w in low for w in INJURY_WORDS):
        tags.append("injury")
    if any(w in low for w in SUSPENSION_WORDS):
        tags.append("suspension")
    if any(w in low for w in MANAGER_WORDS):
        tags.append("manager")
    if any(w in low for w in LINEUP_WORDS):
        tags.append("lineup")
    if any(w in low for w in TACTICAL_WORDS):
        tags.append("tactical")
    if any(w in low for w in WEATHER_WORDS):
        tags.append("conditions")
    return tags


def _query(team: str, sport: str) -> str:
    if sport == "cricket":
        return f'"{team}" (injury OR injured OR "ruled out" OR squad OR suspension OR pitch)'
    return f'"{team}" (injury OR injured OR suspension OR "team news" OR lineup OR manager)'


def parse_rss(xml: str, limit: int = 12) -> list[dict]:
    items: list[dict] = []
    try:
        root = ET.fromstring(xml)
    except Exception:
        return items
    for item in root.iter("item"):
        title = _clean(item.findtext("title") or "")
        link = (item.findtext("link") or "").strip()
        desc = _clean(item.findtext("description") or "")
        pub = item.findtext("pubDate") or ""
        try:
            published = parsedate_to_datetime(pub).astimezone(timezone.utc).isoformat()
        except Exception:
            published = pub
        source = _clean(item.findtext("source") or "")
        if not title:
            continue
        items.append({
            "title": title, "url": link, "source": source or "Google News",
            "published": published, "snippet": desc[:360],
            "tags": classify(title + " " + desc),
        })
        if len(items) >= limit:
            break
    return items


def _cache_key(team: str, sport: str) -> str:
    return "news:" + hashlib.sha1(f"{sport}:{team}".encode()).hexdigest()


async def fetch_team_news(client: httpx.AsyncClient, team: str, sport: str,
                          ttl_minutes: int | None = None) -> list[dict]:
    ttl = settings.news_ttl_minutes if ttl_minutes is None else ttl_minutes
    key = _cache_key(team, sport)
    cached = db.cache_get(key, ttl)
    if cached is not None:
        return cached
    q = _query(team, sport)
    from urllib.parse import quote_plus
    url = f"{GOOGLE}?q={quote_plus(q)}&hl=en-US&gl=US&ceid=US:en"
    try:
        xml = await fetch_text(client, url, cache_key="google:" + key, ttl=ttl * 60, retries=2)
        items = parse_rss(xml, limit=10)
    except Exception:
        items = []
    db.cache_set(key, None, team, items, source="google_news")
    return items


async def fetch_league_news(client: httpx.AsyncClient, league_slug: str) -> list[dict]:
    try:
        from .http import fetch_json
        payload = await fetch_json(client, ESPN.format(league=league_slug),
                                   cache_key=f"espn:news:{league_slug}", ttl=1800)
    except Exception:
        return []
    out = []
    for a in (payload.get("articles") or [])[:8]:
        title = a.get("headline") or ""
        desc = a.get("description") or ""
        out.append({
            "title": title, "url": (a.get("links") or {}).get("web", {}).get("href", ""),
            "source": "ESPN", "published": a.get("published") or "",
            "snippet": _clean(desc)[:360], "tags": classify(title + " " + desc),
        })
    return out


async def research_teams(teams: list[tuple[str, str]], limit: int = 40) -> dict[str, list[dict]]:
    """Fetch news for teams, bounded and cached. teams = [(name, sport)]."""
    async with make_client() as client:
        import asyncio
        sem = asyncio.Semaphore(4)

        async def one(item):
            name, sport = item
            async with sem:
                return name, await fetch_team_news(client, name, sport)

        pairs = await asyncio.gather(*(one(t) for t in teams[:limit]), return_exceptions=True)
    out: dict[str, list[dict]] = {}
    for pair in pairs:
        if isinstance(pair, tuple):
            out[pair[0]] = pair[1]
    return out


def keywords_from_news(items: list[dict]) -> dict[str, Any]:
    tags: dict[str, int] = {}
    sources = set()
    for item in items:
        for tag in item.get("tags") or []:
            tags[tag] = tags.get(tag, 0) + 1
        if item.get("source"):
            sources.add(item["source"])
    return {"tags": tags, "sources": sorted(sources), "count": len(items)}
