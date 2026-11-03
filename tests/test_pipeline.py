"""Regression tests for the defects recorded in docs/baseline_metrics.md.

No network: the Mesonet is replaced by a fake that behaves like the real
service, including its exclusive end date.
"""

from __future__ import annotations

import datetime as dt
import json
import urllib.parse
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, mock

from src import features, learn, main, nwp, upstream, weather


def _normals() -> dict:
    tmax: dict[str, float] = {}
    day = dt.date(2026, 1, 1)
    while day.year == 2026:
        tmax[f"{day.month:02d}-{day.day:02d}"] = 70.0
        day += dt.timedelta(days=1)
    return {"tmax": tmax, "tmin": {key: 50.0 for key in tmax}}


def _observations(start: dt.date, end: dt.date) -> dict:
    rows: dict[dt.date, dict] = {}
    day = start
    while day <= end:
        offset = (day - start).days
        rows[day] = {
            "tmax": 60.0 + offset % 11,
            "tmin": 45.0 + offset % 7,
            "precip": 0.0 if offset % 3 else 0.2,
        }
        day += dt.timedelta(days=1)
    return rows


class _Response:
    def __init__(self, body: str) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _mesonet(available: set[dt.date], value: float = 60.0):
    """urlopen stand-in that drops the end date, the way the Mesonet does."""
    calls: list[tuple[dt.date, dt.date]] = []

    def fake_urlopen(request, timeout=None):
        params = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(request.full_url).query))
        start = dt.date(int(params["year1"]), int(params["month1"]), int(params["day1"]))
        end = dt.date(int(params["year2"]), int(params["month2"]), int(params["day2"]))
        calls.append((start, end))
        lines = ["station,valid,tmpf"]
        for day in sorted(available):
            if start <= day < end:  # exclusive, exactly like the real service
                for hour in range(6):
                    lines.append(f"{params['station']},{day.isoformat()} {hour:02d}:53,{value}")
        return _Response("\n".join(lines) + "\n")

    return fake_urlopen, calls


class LiveFeatureTest(TestCase):
    def test_live_prediction_uses_the_upstream_air(self):
        observations = _observations(dt.date(2026, 1, 1), dt.date(2026, 3, 31))
        normals = _normals()
        air = {day: 55.0 + day.day % 5 for day in observations}
        target = dt.date(2026, 4, 1)
        air[target] = 92.5
        air[target - dt.timedelta(days=1)] = 71.0

        rows = learn.build_dataset(observations, normals, air)
        found = learn.predict_live(rows, observations, target, normals, air)["features"]

        self.assertEqual(found["upstream_overnight"], 92.5)
        self.assertEqual(
            found["upstream_vs_charlotte"],
            round(92.5 - observations[target - dt.timedelta(days=1)]["tmax"], 2),
        )
        self.assertEqual(found["upstream_change"], round(92.5 - 71.0, 2))

    def test_features_ignore_everything_on_or_after_the_target(self):
        observations = _observations(dt.date(2026, 1, 1), dt.date(2026, 3, 31))
        normals = _normals()
        air = {day: 55.0 + day.day % 5 for day in observations}
        target = dt.date(2026, 3, 15)

        full = features.vector(observations, target, normals, air)
        truncated = features.vector(
            {day: row for day, row in observations.items() if day < target},
            target, normals, air,
        )

        self.assertIsNotNone(full)
        self.assertEqual(full, truncated)


class UpstreamCacheTest(TestCase):
    def test_the_last_requested_day_is_kept(self):
        available = {dt.date(2026, 1, 1) + dt.timedelta(days=offset) for offset in range(10)}
        fake, _ = _mesonet(available)

        with TemporaryDirectory() as folder, mock.patch("urllib.request.urlopen", fake):
            days = upstream.ensure(Path(folder) / "upstream.json",
                                   dt.date(2026, 1, 1), dt.date(2026, 1, 10))

        self.assertIn(dt.date(2026, 1, 10), days)
        self.assertEqual(len(days), 10)

    def test_a_missing_day_stays_outside_the_cache_and_is_asked_for_again(self):
        head = {dt.date(2026, 1, 1) + dt.timedelta(days=offset) for offset in range(9)}
        fake, _ = _mesonet(head)

        with TemporaryDirectory() as folder:
            path = Path(folder) / "upstream.json"
            with mock.patch("urllib.request.urlopen", fake):
                days = upstream.ensure(path, dt.date(2026, 1, 1), dt.date(2026, 1, 10))

            self.assertNotIn(dt.date(2026, 1, 10), days)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["covered"]["to"],
                             "2026-01-09")

            later, calls = _mesonet(head | {dt.date(2026, 1, 10)})
            with mock.patch("urllib.request.urlopen", later):
                days = upstream.ensure(path, dt.date(2026, 1, 1), dt.date(2026, 1, 10))

        self.assertIn(dt.date(2026, 1, 10), days)
        self.assertEqual(calls[0][0], dt.date(2026, 1, 10))


class LoggingTest(TestCase):
    def test_the_first_forecast_wins(self):
        entries: dict = {}
        target = dt.date(2026, 11, 3)
        issued = dt.date(2026, 11, 3)
        first = {"tmax": 70.0, "tmin": 54.0, "pop": 0.52, "precip_in": 0.07}
        second = {"tmax": 66.7, "tmin": 51.0, "pop": 0.30, "precip_in": 0.02}

        self.assertTrue(main._record_prediction(entries, target, first, issued))
        self.assertFalse(main._record_prediction(entries, target, second, issued))

        self.assertEqual(entries["2026-11-03"]["tmax"], 70.0)
        self.assertEqual(entries["2026-11-03"]["issued"], "2026-11-03")
        self.assertIn("logged_at", entries["2026-11-03"])

    def test_a_backcast_is_not_logged(self):
        entries: dict = {}
        prediction = {"tmax": 70.0, "tmin": 54.0, "pop": 0.52, "precip_in": 0.07}

        self.assertFalse(main._record_prediction(
            entries, dt.date(2026, 11, 2), prediction, dt.date(2026, 11, 3)))
        self.assertEqual(entries, {})


class GapFillTest(TestCase):
    def test_a_hole_is_filled_from_the_past_only(self):
        earlier = dt.date(2026, 1, 8)
        hole = dt.date(2026, 1, 9)
        later = dt.date(2026, 1, 10)
        rows = {
            earlier: {"tmax": 40.0, "tmin": 30.0, "precip": 0.0},
            later: {"tmax": 100.0, "tmin": 90.0, "precip": 0.0},
        }

        filled = weather._interpolate_gaps(rows)
        self.assertEqual(filled[hole]["tmax"], 40.0)

        rows[later]["tmax"] = 20.0
        self.assertEqual(weather._interpolate_gaps(rows)[hole]["tmax"], 40.0)


class NwpParseTest(TestCase):
    def test_a_full_day_becomes_its_extremes(self):
        hours = [f"2026-01-05T{hour:02d}:00" for hour in range(24)]
        payload = {"hourly": {
            "time": hours,
            "temperature_2m_previous_day1": [50.0 + hour for hour in range(24)],
            "temperature_2m_previous_day2": [40.0 + hour for hour in range(24)],
        }}

        day = nwp._parse(json.dumps(payload))[dt.date(2026, 1, 5)]

        self.assertEqual(day["tmax"], 73.0)
        self.assertEqual(day["tmin"], 50.0)
        self.assertEqual(day["tmax_day2"], 63.0)

    def test_a_thin_day_is_dropped(self):
        payload = {"hourly": {
            "time": ["2026-01-05T00:00", "2026-01-05T01:00"],
            "temperature_2m_previous_day1": [50.0, 51.0],
            "temperature_2m_previous_day2": [None, None],
        }}

        self.assertEqual(nwp._parse(json.dumps(payload)), {})


class NwpCacheTest(TestCase):
    def test_coverage_is_written_from_the_days_that_arrived(self):
        def fake_fetch(start, end, tries=3, timeout=180):
            stamps = []
            cursor = start
            while cursor <= end:
                stamps.extend(f"{cursor.isoformat()}T{hour:02d}:00" for hour in range(24))
                cursor += dt.timedelta(days=1)
            return json.dumps({"hourly": {
                "time": stamps,
                "temperature_2m_previous_day1": [60.0] * len(stamps),
                "temperature_2m_previous_day2": [55.0] * len(stamps),
            }})

        with TemporaryDirectory() as folder, mock.patch("src.nwp._fetch", fake_fetch):
            path = Path(folder) / "nwp.json"
            days = nwp.ensure(path, dt.date(2026, 1, 1), dt.date(2026, 1, 5))
            covered = json.loads(path.read_text(encoding="utf-8"))["covered"]

        self.assertEqual(len(days), 5)
        self.assertEqual(covered, {"from": "2026-01-01", "to": "2026-01-05"})


class NwpFeatureTest(TestCase):
    def test_the_forecast_block_appears_only_when_supplied(self):
        observations = _observations(dt.date(2026, 1, 1), dt.date(2026, 3, 31))
        normals = _normals()
        air = {day: 55.0 for day in observations}
        target = dt.date(2026, 4, 1)
        forecast = {
            target: {"tmax": 88.0, "tmin": 60.0},
            target - dt.timedelta(days=1): {"tmax": 80.0, "tmin": 55.0},
        }

        plain = features.vector(observations, target, normals, air)
        enriched = features.vector(observations, target, normals, air, forecast)

        self.assertEqual(len(plain), len(features.FEATURES))
        self.assertEqual(len(enriched), len(features.FEATURES) + len(features.NWP_FEATURES))
        block = dict(zip(features.NWP_FEATURES, enriched[-4:]))
        self.assertEqual(block["nwp_tmax"], 88.0)
        self.assertEqual(block["nwp_tmin"], 60.0)
        self.assertEqual(block["nwp_trend"], 8.0)
        self.assertEqual(
            block["nwp_vs_lag1"],
            88.0 - observations[target - dt.timedelta(days=1)]["tmax"],
        )

    def test_forecasts_after_the_target_do_not_change_the_vector(self):
        observations = _observations(dt.date(2026, 1, 1), dt.date(2026, 3, 31))
        normals = _normals()
        air = {day: 55.0 for day in observations}
        target = dt.date(2026, 3, 15)
        forecast = {day: {"tmax": 60.0 + day.day, "tmin": 40.0 + day.day}
                    for day in sorted(observations)}

        trimmed = {day: value for day, value in forecast.items() if day <= target}

        self.assertEqual(
            features.vector(observations, target, normals, air, forecast),
            features.vector(observations, target, normals, air, trimmed),
        )
