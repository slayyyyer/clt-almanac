"""What the models said yesterday about today.

Open-Meteo's Previous Runs API stores each forecast at fixed lead-time offsets,
so `temperature_2m_previous_day1` is the value that was predicted 24 hours
before it verified. A 07:17Z run could have read exactly that the morning
before, which makes it the first input in this project that is a forecast
rather than a measurement of what has already happened.

The daily endpoint ignores the `_previous_dayN` suffix, so daily highs and lows
are aggregated here from hourly temperatures. A day is kept only when most of
its hours arrived, which keeps DST from silently dropping two days a year.
"""

from __future__ import annotations

import datetime as dt
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

ENDPOINT = "https://previous-runs-api.open-meteo.com/v1/forecast"
USER_AGENT = "clt-almanac/1.0 (personal Charlotte weather almanac)"

LATITUDE = 35.2271
LONGITUDE = -80.8431
TIMEZONE = "America/New_York"

# One deterministic model, named explicitly: `best_match` recombines models per
# hour, which would make the series something no single model ever issued.
MODEL = "ecmwf_ifs025"
DAY1 = "temperature_2m_previous_day1"
DAY2 = "temperature_2m_previous_day2"

MIN_HOURS = 20  # of 24, so a daylight-saving day still counts
CHUNK_DAYS = 180


def _fetch(start: dt.date, end: dt.date, tries: int = 3, timeout: int = 180) -> str:
    params = {
        "latitude": str(LATITUDE),
        "longitude": str(LONGITUDE),
        "hourly": f"{DAY1},{DAY2}",
        "temperature_unit": "fahrenheit",
        "timezone": TIMEZONE,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "models": MODEL,
    }
    url = f"{ENDPOINT}?{urllib.parse.urlencode(params)}"
    last_error: Exception | None = None
    for attempt in range(tries):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read().decode("utf-8", "replace")
        except Exception as error:  # noqa: BLE001 - retried, then surfaced
            last_error = error
            if attempt < tries - 1:
                time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"previous-runs request failed: {start}..{end}") from last_error


def _parse(text: str) -> dict[dt.date, dict]:
    """Daily max/min of the day-before forecast, keyed by the day it verifies."""
    payload = json.loads(text)
    hourly = payload.get("hourly") or {}
    stamps = hourly.get("time") or []
    day1 = hourly.get(DAY1) or []
    day2 = hourly.get(DAY2) or []

    buckets: dict[dt.date, dict[str, list[float]]] = {}
    for index, stamp in enumerate(stamps):
        try:
            day = dt.date.fromisoformat(stamp[:10])
        except (TypeError, ValueError):
            continue
        bucket = buckets.setdefault(day, {"day1": [], "day2": []})
        for key, series in (("day1", day1), ("day2", day2)):
            if index < len(series) and series[index] is not None:
                bucket[key].append(float(series[index]))

    days: dict[dt.date, dict] = {}
    for day, bucket in buckets.items():
        if len(bucket["day1"]) < MIN_HOURS:
            continue
        days[day] = {
            "tmax": round(max(bucket["day1"]), 2),
            "tmin": round(min(bucket["day1"]), 2),
            "tmax_day2": (round(max(bucket["day2"]), 2)
                          if len(bucket["day2"]) >= MIN_HOURS else None),
        }
    return days


def _pull(days: dict[dt.date, dict], start: dt.date, end: dt.date) -> None:
    if end < start:
        return
    cursor = start
    while cursor <= end:
        stop = min(cursor + dt.timedelta(days=CHUNK_DAYS - 1), end)
        days.update(_parse(_fetch(cursor, stop)))
        cursor = stop + dt.timedelta(days=1)


def ensure(path: Path, start: dt.date, end: dt.date) -> dict[dt.date, dict]:
    """Cached day-ahead forecasts, extended as needed.

    Coverage is derived from the days that actually arrived, so a span the
    service had no data for is asked for again rather than written off.
    """
    payload: dict = {}
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            payload = {}

    days = {
        dt.date.fromisoformat(key): value
        for key, value in (payload.get("days") or {}).items()
    }
    before = dict(days)

    if not days:
        _pull(days, start, end)
    else:
        if end > max(days):
            _pull(days, max(days) + dt.timedelta(days=1), end)
        if start < min(days):
            _pull(days, start, min(days) - dt.timedelta(days=1))

    covered = ({"from": min(days).isoformat(), "to": max(days).isoformat()}
               if days else None)

    if days and (days != before or payload.get("covered") != covered):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({
                "source": f"Open-Meteo previous runs · {MODEL} · day-1 lead",
                "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                "covered": covered,
                "days": {
                    day.isoformat(): value for day, value in sorted(days.items())
                },
            }, indent=1),
            encoding="utf-8",
        )

    return days
