"""Open-Meteo weather and geocoding adapter (no API key)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from .. import db
from .http import fetch_json, make_client

GEO = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST = "https://api.open-meteo.com/v1/forecast"


async def geocode(city: str) -> dict | None:
    if not city:
        return None
    key = "geo:" + city.lower().strip()
    cached = db.cache_get(key, 60 * 24 * 30)
    if cached is not None:
        return cached or None
    async with make_client() as client:
        try:
            payload = await fetch_json(
                client, f"{GEO}?name={city}&count=1&language=en&format=json",
                cache_key=key, ttl=60 * 60 * 24 * 30,
            )
            results = payload.get("results") or []
            result = results[0] if results else None
        except Exception:
            result = None
    db.cache_set(key, None, city, [result] if result else [], source="open-meteo-geocode")
    return result


async def forecast(lat: float, lon: float, kickoff_iso: str) -> dict:
    if lat is None or lon is None:
        return {}
    try:
        ko = datetime.fromisoformat(kickoff_iso.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return {}
    key = f"weather:{round(lat, 3)}:{round(lon, 3)}:{ko.strftime('%Y%m%d%H')}"
    cached = db.cache_get(key, 180)
    if cached is not None:
        return cached[0] if cached else {}
    async with make_client() as client:
        try:
            payload = await fetch_json(
                client,
                (f"{FORECAST}?latitude={lat}&longitude={lon}"
                 "&hourly=temperature_2m,precipitation_probability,precipitation,"
                 "wind_speed_10m,relative_humidity_2m,cloud_cover,apparent_temperature"
                 "&forecast_days=7&timezone=UTC"),
                cache_key=key, ttl=1800,
            )
        except Exception:
            return {}
    hourly = payload.get("hourly") or {}
    times = hourly.get("time") or []
    if not times:
        return {}
    target = ko.replace(minute=0, second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M")
    idx = 0
    best = None
    for i, t in enumerate(times):
        if t == target:
            idx = i
            best = i
            break
        try:
            dt = datetime.fromisoformat(t).replace(tzinfo=timezone.utc)
            delta = abs((dt - ko).total_seconds())
            if best is None or delta < best[0]:
                best = (delta, i)
        except Exception:
            continue
    if best and not target:
        idx = best[1]
    elif best and times[idx] != target:
        idx = best[1]

    def val(name):
        arr = hourly.get(name) or []
        return arr[idx] if idx < len(arr) else None

    result = {
        "temperature_c": val("temperature_2m"), "apparent_c": val("apparent_temperature"),
        "precip_prob": val("precipitation_probability"), "precipitation_mm": val("precipitation"),
        "wind_kph": val("wind_speed_10m"), "humidity": val("relative_humidity_2m"),
        "cloud_cover": val("cloud_cover"), "time": times[idx] if idx < len(times) else None,
        "source": "Open-Meteo", "kind": "forecast",
    }
    db.cache_set(key, None, None, [result], source="open-meteo")
    return result


def classify_football(w: dict) -> dict:
    if not w:
        return {}
    rain = float(w.get("precipitation_mm") or 0)
    wind = float(w.get("wind_kph") or 0)
    temp = float(w.get("temperature_c") or 15)
    flags = []
    goal_effect = 0.0
    if rain >= 2 or float(w.get("precip_prob") or 0) >= 60:
        flags.append("wet pitch")
        goal_effect -= 0.04
    if wind >= 30:
        flags.append("strong wind")
        goal_effect -= 0.03
    if temp >= 30:
        flags.append("heat load")
        goal_effect -= 0.02
    if temp <= 2:
        flags.append("freezing")
    return {"flags": flags, "goal_effect": round(goal_effect, 3),
            "summary": ", ".join(flags) if flags else "benign conditions"}


def classify_cricket(w: dict, format_type: str = "T20") -> dict:
    if not w:
        return {}
    humidity = float(w.get("humidity") or 0)
    rain = float(w.get("precipitation_mm") or 0)
    temp = float(w.get("temperature_c") or 25)
    dew = humidity >= 75 and temp >= 20
    flags = []
    if dew:
        flags.append("dew risk (second innings)")
    if rain >= 1:
        flags.append("rain interruption risk")
    if temp >= 35:
        flags.append("extreme heat")
    return {
        "dew_risk": round(min(1.0, max(0.0, (humidity - 60) / 35)), 2) if dew else 0.0,
        "flags": flags, "summary": ", ".join(flags) if flags else "dry, stable conditions",
    }
