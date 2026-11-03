"""The air coming at Charlotte, from hourly airport observations.

GHCN gives the airport one summary row per day, which is why the model has only
ever known what already happened here. The Iowa Environmental Mesonet keeps the
hourly records from the airports around us, so the model can also see the air
mass that has not arrived yet: Atlanta to the southwest, Greer to the west,
Columbia to the south, Asheville to the northwest.

The window is 00Z to 05Z, the overnight hours that are on the wire before the
07:17Z run. That is the point: a reader could have had this information at
press time, so the backtest and the live forecast are built from the same kind
of evidence.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

ENDPOINT = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py"
USER_AGENT = "clt-almanac/1.0 (personal Charlotte weather almanac)"

# Upstream airports, in the direction Charlotte's weather usually arrives from.
STATIONS = ("KATL", "KGSP", "KCAE", "KAVL")

MIN_HOURS = 4  # of six overnight reports before a station-day counts
MIN_STATIONS = 2  # of four before the region counts as observed

WINDOW = range(0, 6)  # 00Z-05Z


def _fetch(station: str, start: dt.date, end: dt.date, tries: int = 3,
           timeout: int = 180) -> str:
    # The Mesonet treats the end date as exclusive: asking for 10-29..11-02
    # returns 10-29 through 11-01. Ask one day past the span we want and let
    # `_pull` keep only the days inside it.
    stop = end + dt.timedelta(days=1)
    params = {
        "station": station,
        "data": "tmpf",
        "year1": str(start.year),
        "month1": str(start.month),
        "day1": str(start.day),
        "year2": str(stop.year),
        "month2": str(stop.month),
        "day2": str(stop.day),
        "tz": "UTC",
        "format": "onlycomma",
        "missing": "M",
        "trace": "T",
        "direct": "no",
        "report_type": "3",
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
    raise RuntimeError(f"IEM request failed: {station} {start}..{end}") from last_error


def _station_days(text: str) -> dict[dt.date, float]:
    """Mean 00Z-05Z temperature for each day this station reported."""
    buckets: dict[dt.date, list[float]] = {}
    for record in csv.DictReader(io.StringIO(text)):
        try:
            stamp = dt.datetime.strptime(record["valid"], "%Y-%m-%d %H:%M")
        except (KeyError, TypeError, ValueError):
            continue
        if stamp.hour not in WINDOW:
            continue
        raw = (record.get("tmpf") or "").strip()
        if raw in ("", "M"):
            continue
        try:
            buckets.setdefault(stamp.date(), []).append(float(raw))
        except ValueError:
            continue
    return {
        day: sum(values) / len(values)
        for day, values in buckets.items()
        if len(values) >= MIN_HOURS
    }


def _days(start: dt.date, end: dt.date):
    day = start
    while day <= end:
        yield day
        day += dt.timedelta(days=1)


def _pull(days: dict[dt.date, float], start: dt.date, end: dt.date) -> bool:
    """Fetch one span and merge it into `days`. True if any station answered."""
    if end < start:
        return False
    responded = False
    tables = []
    for station in STATIONS:
        try:
            tables.append(_station_days(_fetch(station, start, end)))
            responded = True
        except Exception:  # noqa: BLE001 - one dead station must not sink the run
            tables.append({})
    for day in _days(start, end):
        values = [table[day] for table in tables if day in table]
        if len(values) >= MIN_STATIONS:
            days[day] = round(sum(values) / len(values), 2)
    return responded


def ensure(path: Path, start: dt.date, end: dt.date) -> dict[dt.date, float]:
    """Regional overnight temperature, cached on disk and extended as needed.

    The committed cache keeps the daily job from refetching two decades of
    hourly records; a normal run asks each station for a handful of new days.
    """
    payload: dict = {}
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            payload = {}

    days = {
        dt.date.fromisoformat(key): float(value)
        for key, value in (payload.get("days") or {}).items()
    }
    before = dict(days)

    # Coverage is read back from the values that actually arrived, never from
    # the dates that were asked for. A day the Mesonet had no report for stays
    # outside the edge of the cache and is requested again on the next run.
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
                "source": "Iowa Environmental Mesonet ASOS · " + "/".join(STATIONS),
                "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                "covered": covered,
                "days": {day.isoformat(): value for day, value in sorted(days.items())},
            }, indent=1),
            encoding="utf-8",
        )

    return days
