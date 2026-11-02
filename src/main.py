"""Build one day's almanac: fetch, learn, predict, narrate, publish."""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

from . import learn, narrative, site, weather

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
PUBLIC_DIR = ROOT / "public"
NORMALS_PATH = DATA_DIR / "normals.json"
PREDICTIONS_PATH = DATA_DIR / "predictions.jsonl"
HISTORY_START = dt.date(2005, 1, 1)
MODEL_VERSION = "ridge-logistic-v1"


def _load_predictions() -> dict[str, dict]:
    if not PREDICTIONS_PATH.exists():
        return {}
    entries: dict[str, dict] = {}
    for line in PREDICTIONS_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            entries[entry["target"]] = entry
        except (json.JSONDecodeError, KeyError):
            continue
    return entries


def _save_predictions(entries: dict[str, dict]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ordered = [entries[key] for key in sorted(entries)][-730:]
    PREDICTIONS_PATH.write_text(
        "\n".join(json.dumps(entry, sort_keys=True) for entry in ordered) + "\n",
        encoding="utf-8",
    )


def _resolve(entries: dict[str, dict], observations: dict) -> list[dict]:
    resolved = []
    for key in sorted(entries):
        entry = entries[key]
        try:
            day = dt.date.fromisoformat(entry["target"])
        except (KeyError, ValueError):
            continue
        actual = observations.get(day)
        if not actual or actual.get("tmax") is None or actual.get("tmin") is None:
            continue
        resolved.append({
            **entry,
            "actual_tmax": actual["tmax"],
            "actual_tmin": actual["tmin"],
            "actual_precip": actual.get("precip"),
        })
    return resolved


def _live_skill(resolved: list[dict]) -> dict | None:
    if not resolved:
        return None
    count = len(resolved)
    return {
        "count": count,
        "high_mae": round(sum(abs(r["tmax"] - r["actual_tmax"]) for r in resolved) / count, 1),
        "low_mae": round(sum(abs(r["tmin"] - r["actual_tmin"]) for r in resolved) / count, 1),
        "brier": round(
            sum((r["pop"] - (1.0 if (r["actual_precip"] or 0.0) >= 0.01 else 0.0)) ** 2
                for r in resolved) / count,
            3,
        ),
    }


def _narrative_context(prediction: dict, official: dict | None, latest: dt.date) -> dict:
    yesterday = prediction.get("yesterday") or {}
    context = {
        "date": prediction["target"].isoformat(),
        "place": "Charlotte, North Carolina",
        "predicted_high_f": prediction["tmax"],
        "predicted_low_f": prediction["tmin"],
        "chance_of_rain_percent": round(prediction["pop"] * 100),
        "expected_rain_inches": prediction["precip_in"],
        "normal_high_f": prediction["normal_tmax"],
        "normal_low_f": prediction["normal_tmin"],
        "observed_through": latest.isoformat(),
        "yesterday_high_f": yesterday.get("tmax"),
        "yesterday_low_f": yesterday.get("tmin"),
        "yesterday_rain_inches": yesterday.get("precip"),
        "seven_day_mean_high_f": prediction.get("week_mean_high"),
        "rain_last_14_days_inches": prediction.get("recent_rain_in"),
    }
    if official:
        context["open_meteo_forecast"] = {
            "high_f": official.get("tmax"),
            "low_f": official.get("tmin"),
        }
    return context


def _facts(prediction: dict) -> list[dict]:
    yesterday = prediction.get("yesterday") or {}
    facts = []
    if yesterday.get("tmax") is not None:
        rain = yesterday.get("precip")
        value = f"{round(yesterday['tmax'])}° / {round(yesterday['tmin'])}°"
        if rain:
            value += f" · {rain:.2f} in"
        facts.append({"label": "Yesterday", "value": value})

    if prediction.get("week_mean_high") is not None:
        facts.append({"label": "Past 7 days, mean high", "value": f"{prediction['week_mean_high']:.0f}°"})

    if prediction.get("recent_rain_in") is not None:
        facts.append({"label": "Rain, last 14 days", "value": f"{prediction['recent_rain_in']:.2f} in"})

    if prediction.get("normal_tmax") is not None:
        delta = prediction["tmax"] - prediction["normal_tmax"]
        sign = "+" if delta >= 0 else "−"
        facts.append({"label": "Against normal high", "value": f"{sign}{abs(delta):.0f}°"})

    return facts


def _chart_days(observations: dict, resolved: list[dict], count: int = 30) -> list[dict]:
    scored = {entry["target"]: entry for entry in resolved}
    days = []
    for day in sorted(observations)[-count:]:
        row = observations[day]
        if row.get("tmax") is None or row.get("tmin") is None:
            continue
        entry = scored.get(day.isoformat())
        days.append({
            "date": day.isoformat(),
            "tmax": row["tmax"],
            "tmin": row["tmin"],
            "predicted_tmax": entry["tmax"] if entry else None,
        })
    return days


def _week_rows(observations: dict, prediction: dict, target: dt.date) -> list[dict]:
    rows = []
    for offset in range(6, 0, -1):
        day = target - dt.timedelta(days=offset)
        row = observations.get(day)
        if not row or row.get("tmax") is None:
            continue
        rows.append({
            "label": day.strftime("%a %b ") + str(day.day),
            "tmax": row["tmax"],
            "tmin": row["tmin"],
            "precip": row.get("precip"),
            "is_prediction": False,
        })
    rows.append({
        "label": f"{target.strftime('%a %b')} {target.day} · forecast",
        "tmax": prediction["tmax"],
        "tmin": prediction["tmin"],
        "precip": prediction["precip_in"] if prediction["pop"] >= 0.15 else 0.0,
        "is_prediction": True,
    })
    return rows


def build(args: argparse.Namespace) -> dict:
    normals = weather.load_normals(NORMALS_PATH, refresh=args.refresh_normals)
    observations, forecast, sources = weather.fetch_observations(HISTORY_START)
    if not observations:
        raise SystemExit("no observations available")

    latest = max(observations)
    target = latest + dt.timedelta(days=1)

    rows = learn.build_dataset(observations, normals)
    if len(rows) < 400:
        raise SystemExit(f"not enough history to train on ({len(rows)} rows)")

    skill = learn.backtest(rows, horizon=args.days)
    prediction = learn.predict_live(rows, observations, target, normals)
    official = forecast.get(target)

    context = _narrative_context(prediction, official, latest)
    note = narrative.write(context, allow_api=not args.no_narrative)

    entries = _load_predictions()
    entries[target.isoformat()] = {
        "target": target.isoformat(),
        "issued": weather.local_today().isoformat(),
        "tmax": prediction["tmax"],
        "tmin": prediction["tmin"],
        "pop": prediction["pop"],
        "precip_in": prediction["precip_in"],
        "model": MODEL_VERSION,
    }
    _save_predictions(entries)

    resolved = _resolve(entries, observations)
    now = dt.datetime.now(dt.timezone.utc)

    state = {
        "target_date": target.isoformat(),
        "latest_observation": latest.isoformat(),
        "generated_label": now.strftime("%B ") + str(now.day) + now.strftime(", %Y at %H:%M UTC"),
        "model_version": MODEL_VERSION,
        "prediction": {
            **{key: prediction[key] for key in
               ("tmax", "tmin", "pop", "precip_in", "normal_tmax", "normal_tmin")},
            "target_date": target.isoformat(),
        },
        "official": official,
        "narrative": note,
        "skill": skill,
        "live": _live_skill(resolved),
        "facts": _facts(prediction),
        "week": _week_rows(observations, prediction, target),
        "days": _chart_days(observations, resolved),
        "sources": sources,
        "normals_source": normals.get("source", ""),
        "backcast_days": max(0, (weather.local_today() - target).days),
    }

    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    (PUBLIC_DIR / "index.html").write_text(site.render(state), encoding="utf-8")
    (PUBLIC_DIR / "forecast.json").write_text(
        json.dumps({"state": state, "resolved": resolved}, indent=2, default=str),
        encoding="utf-8",
    )
    return state


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the Charlotte almanac.")
    parser.add_argument("--days", type=int, default=learn.BACKTEST_DAYS,
                        help="walk-forward backtest window in days")
    parser.add_argument("--no-narrative", action="store_true",
                        help="skip the z.ai call and use the built-in template")
    parser.add_argument("--refresh-normals", action="store_true",
                        help="refetch the 1991-2020 normals instead of using data/normals.json")
    args = parser.parse_args(argv)

    state = build(args)
    prediction = state["prediction"]
    skill = state["skill"]
    print(f"Charlotte NC {state['target_date']}: high {prediction['tmax']:.0f}F "
          f"low {prediction['tmin']:.0f}F, rain {prediction['pop'] * 100:.0f}%")
    print(f"backtest {skill['days']} days: high MAE {skill['high']['model']}F "
          f"(persistence {skill['high']['persistence']}F, normal {skill['high']['climatology']}F)")
    print(f"narrative: {state['narrative']['source']}")
    if state["live"]:
        print(f"live log: {state['live']['count']} scored predictions")
    print(f"wrote {PUBLIC_DIR / 'index.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
