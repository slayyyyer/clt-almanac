"""Charlotte weather, from two free and keyless sources.

History comes from NOAA's GHCN-Daily record for Charlotte Douglas International
Airport (station USW00013881): real station observations, 1939 to now, usually
two to four days behind. The last few days and the days ahead come from
Open-Meteo's forecast API, which also stands in as a history source if NCEI is
unreachable.
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
from zoneinfo import ZoneInfo

LATITUDE = 35.2271
LONGITUDE = -80.8431
TIMEZONE = "America/New_York"
PLACE = "Charlotte, North Carolina"

GHCN_STATION = "USW00013881"
GHCN_URL = (
    "https://www.ncei.noaa.gov/data/global-historical-climatology-network-daily/"
    f"access/{GHCN_STATION}.csv"
)

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

USER_AGENT = "clt-almanac/1.0 (personal Charlotte weather almanac)"

TMAX = "temperature_2m_max"
TMIN = "temperature_2m_min"
PRECIP = "precipitation_sum"
DAILY_VARS = (TMAX, TMIN, PRECIP)

_GHCN_ROWS: dict[dt.date, dict] | None = None


def local_today() -> dt.date:
    """Today's date in Charlotte, regardless of where this runs."""
    return dt.datetime.now(dt.timezone.utc).astimezone(ZoneInfo(TIMEZONE)).date()


def _fetch(url: str, tries: int = 3, timeout: int = 120) -> str:
    last_error: Exception | None = None
    for attempt in range(tries):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read().decode("utf-8", "replace")
        except Exception as error:  # noqa: BLE001 - retried, then re-raised
            last_error = error
            if attempt < tries - 1:
                time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"request failed: {url}") from last_error


def _fetch_json(url: str) -> dict:
    return json.loads(_fetch(url))


def _query(endpoint: str, start: dt.date | None = None, end: dt.date | None = None,
           past_days: int | None = None, forecast_days: int | None = None) -> str:
    params: dict[str, str] = {
        "latitude": str(LATITUDE),
        "longitude": str(LONGITUDE),
        "daily": ",".join(DAILY_VARS),
        "temperature_unit": "fahrenheit",
        "precipitation_unit": "inch",
        "timezone": TIMEZONE,
    }
    if start is not None:
        params["start_date"] = start.isoformat()
    if end is not None:
        params["end_date"] = end.isoformat()
    if past_days is not None:
        params["past_days"] = str(past_days)
    if forecast_days is not None:
        params["forecast_days"] = str(forecast_days)
    return f"{endpoint}?{urllib.parse.urlencode(params)}"


def _number(value) -> float | None:
    if value in (None, ""):
        return None
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def _tenths_c_to_f(value) -> float | None:
    if value in (None, ""):
        return None
    try:
        tenths = float(value)
    except (TypeError, ValueError):
        return None
    if tenths <= -999:
        return None
    return round(tenths / 10.0 * 9.0 / 5.0 + 32.0, 2)


def _tenths_mm_to_in(value) -> float | None:
    if value in (None, ""):
        return None
    try:
        tenths = float(value)
    except (TypeError, ValueError):
        return None
    if tenths <= -999:
        return None
    return round(tenths / 10.0 / 25.4, 2)


def _ghcn_rows() -> dict[dt.date, dict]:
    """The full station record, parsed once per process."""
    global _GHCN_ROWS
    if _GHCN_ROWS is not None:
        return _GHCN_ROWS

    text = _fetch(GHCN_URL)
    rows: dict[dt.date, dict] = {}
    for record in csv.DictReader(io.StringIO(text)):
        try:
            day = dt.date.fromisoformat(record["DATE"])
        except (KeyError, TypeError, ValueError):
            continue
        rows[day] = {
            "tmax": _tenths_c_to_f(record.get("TMAX")),
            "tmin": _tenths_c_to_f(record.get("TMIN")),
            "precip": _tenths_mm_to_in(record.get("PRCP")),
        }
    if not rows:
        raise RuntimeError("GHCN station record parsed to zero rows")
    _GHCN_ROWS = rows
    return rows


def _open_meteo_window() -> tuple[dict[dt.date, dict], dict[dt.date, dict]]:
    """(recent analysed days, forward forecast days)."""
    today = local_today()
    payload = _fetch_json(_query(FORECAST_URL, past_days=14, forecast_days=3))
    rows = _rows(payload)
    recent = {
        day: row for day, row in rows.items()
        if day <= today - dt.timedelta(days=1) and row["tmax"] is not None
    }
    forecast = {
        day: row for day, row in rows.items()
        if day >= today and row["tmax"] is not None
    }
    return recent, forecast


def _rows(payload: dict) -> dict[dt.date, dict]:
    daily = payload.get("daily") or {}
    times = daily.get("time") or []
    columns = {key: daily.get(key) or [None] * len(times) for key in DAILY_VARS}
    rows: dict[dt.date, dict] = {}
    for index, stamp in enumerate(times):
        try:
            day = dt.date.fromisoformat(stamp)
        except (TypeError, ValueError):
            continue
        rows[day] = {
            "tmax": _number(columns[TMAX][index]),
            "tmin": _number(columns[TMIN][index]),
            "precip": _number(columns[PRECIP][index]),
        }
    return rows


def _interpolate_gaps(rows: dict[dt.date, dict]) -> dict[dt.date, dict]:
    """Fill isolated one-day holes in temperature with a straight line."""
    if not rows:
        return rows
    days = sorted(rows)
    filled = dict(rows)
    cursor = days[0]
    last = days[-1]
    while cursor <= last:
        if cursor not in filled:
            before = cursor - dt.timedelta(days=1)
            after = cursor + dt.timedelta(days=1)
            if before in filled and after in filled:
                previous, following = filled[before], filled[after]
                if None not in (previous["tmax"], following["tmax"]):
                    filled[cursor] = {
                        "tmax": round((previous["tmax"] + following["tmax"]) / 2, 2),
                        "tmin": round(((previous["tmin"] or previous["tmax"]) +
                                       (following["tmin"] or following["tmax"])) / 2, 2),
                        "precip": None,
                    }
        cursor += dt.timedelta(days=1)
    return filled


def fetch_observations(start: dt.date) -> tuple[dict[dt.date, dict], dict[dt.date, dict], dict]:
    """Return (observations, forward forecast, provenance).

    Observations stop at yesterday. Today's daily values are still an estimate,
    and using them would leak the answer into the prediction.
    """
    today = local_today()
    yesterday = today - dt.timedelta(days=1)
    meta: dict = {"history": "", "recent": "", "error": ""}

    try:
        observations = {
            day: row for day, row in _ghcn_rows().items()
            if day >= start and row["tmax"] is not None and row["tmin"] is not None
        }
        meta["history"] = f"NOAA GHCN-Daily · Charlotte Douglas (USW00013881)"
    except Exception as error:  # noqa: BLE001 - fall back below
        observations = {}
        meta["error"] = f"GHCN unavailable: {type(error).__name__}: {error}"[:180]

    try:
        recent, forecast = _open_meteo_window()
        meta["recent"] = "Open-Meteo forecast API"
    except Exception as error:  # noqa: BLE001 - history may still carry the run
        recent, forecast = {}, {}
        meta["error"] = (meta["error"] + " · " if meta["error"] else "") + \
            f"Open-Meteo unavailable: {type(error).__name__}: {error}"[:180]

    if not observations:
        archive_end = today - dt.timedelta(days=7)
        if archive_end > start:
            try:
                payload = _fetch_json(_query(ARCHIVE_URL, start=start, end=archive_end))
                observations = {
                    day: row for day, row in _rows(payload).items()
                    if row["tmax"] is not None and row["tmin"] is not None
                }
                meta["history"] = "Open-Meteo ERA5 archive (fallback)"
            except Exception as error:  # noqa: BLE001 - report, then continue with recent days
                meta["history"] = "Open-Meteo forecast API only (degraded)"
                meta["error"] = (meta["error"] + " · " if meta["error"] else "") + \
                    f"archive unavailable: {type(error).__name__}"[:180]

    if not observations and not recent:
        raise RuntimeError("no weather data available from any source")

    filled = 0
    for day, row in recent.items():
        existing = observations.get(day)
        if day <= yesterday and (existing is None or existing.get("tmax") is None):
            observations[day] = row
            filled += 1
    meta["filled_days"] = filled

    observations = _interpolate_gaps({
        day: row for day, row in observations.items() if day <= yesterday
    })
    if not observations:
        raise RuntimeError("no observations at or before yesterday")
    return observations, forecast, meta


def _smooth(values: list[float], window: int = 15) -> list[float]:
    half = window // 2
    padded = values[-half:] + values + values[:half]
    return [sum(padded[i:i + window]) / window for i in range(len(values))]


def _normals_from_rows(rows: dict[dt.date, dict], first: dt.date, last: dt.date) -> dict | None:
    buckets: dict[str, list[float]] = {}
    for day, row in rows.items():
        if not (first <= day <= last):
            continue
        if row["tmax"] is None or row["tmin"] is None:
            continue
        key = f"{day.month:02d}-{day.day:02d}"
        acc = buckets.setdefault(key, [0.0, 0.0, 0.0, 0.0])
        acc[0] += row["tmax"]
        acc[1] += row["tmin"]
        acc[2] += row["precip"] or 0.0
        acc[3] += 1.0

    averaged = {
        key: [acc[0] / acc[3], acc[1] / acc[3], acc[2] / acc[3]]
        for key, acc in buckets.items()
        if acc[3] >= (last.year - first.year + 1) * 0.5
    }
    if len(averaged) < 300:
        return None

    calendar: list[dt.date] = []
    cursor = dt.date(2000, 1, 1)
    while cursor.year == 2000:
        calendar.append(cursor)
        cursor += dt.timedelta(days=1)

    series: dict[str, list[float]] = {"tmax": [], "tmin": [], "precip": []}
    for day in calendar:
        values = averaged.get(f"{day.month:02d}-{day.day:02d}") or averaged.get(f"{day.month:02d}-28")
        if values is None:
            return None
        series["tmax"].append(values[0])
        series["tmin"].append(values[1])
        series["precip"].append(values[2])

    return {
        name: {
            f"{day.month:02d}-{day.day:02d}": round(value, 2)
            for day, value in zip(calendar, _smooth(values))
        }
        for name, values in series.items()
    }


def load_normals(path: Path, refresh: bool = False) -> dict:
    """1991-2020 daily normals, smoothed over a 15-day window.

    Computed once and committed, so the daily job does not refetch decades of
    records every morning.
    """
    if path.exists() and not refresh:
        return json.loads(path.read_text(encoding="utf-8"))

    first, last = dt.date(1991, 1, 1), dt.date(2020, 12, 31)
    source = ""
    normals = None

    try:
        normals = _normals_from_rows(_ghcn_rows(), first, last)
        source = "NOAA GHCN-Daily 1991-2020 · Charlotte Douglas (USW00013881)"
    except Exception:  # noqa: BLE001 - try the archive next
        normals = None

    if normals is None:
        payload = _fetch_json(_query(ARCHIVE_URL, start=first, end=last))
        normals = _normals_from_rows(_rows(payload), first, last)
        source = "Open-Meteo ERA5 archive 1991-2020"

    if normals is None:
        raise RuntimeError("could not build climate normals from any source")

    result = {
        "source": source,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        **normals,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=1, sort_keys=True), encoding="utf-8")
    return result


def normal_for(normals: dict, variable: str, day: dt.date) -> float | None:
    return normals.get(variable, {}).get(f"{day.month:02d}-{day.day:02d}")
