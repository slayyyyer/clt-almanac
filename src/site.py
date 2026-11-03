"""Render the static almanac page. No JavaScript, no external assets."""

from __future__ import annotations

import datetime as dt
import html

CSS = """
:root {
  --paper: #f7f2e7;
  --paper-deep: #efe7d6;
  --ink: #1d1b17;
  --ink-soft: #5b5548;
  --rule: #d8cfba;
  --green: #1f5c4a;
  --brick: #a8492f;
  --sky: #3c6e9c;
}
* { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; }
body {
  margin: 0;
  background: var(--paper);
  background-image:
    radial-gradient(circle at 18% 8%, rgba(255,255,255,.55), transparent 45%),
    linear-gradient(180deg, rgba(0,0,0,.015), rgba(0,0,0,0) 220px);
  color: var(--ink);
  font-family: "Iowan Old Style", "Palatino Linotype", Palatino, Georgia, serif;
  line-height: 1.55;
}
.wrap { max-width: 780px; margin: 0 auto; padding: 40px 22px 70px; }
.eyebrow {
  font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
  font-size: 11px;
  letter-spacing: .18em;
  text-transform: uppercase;
  color: var(--ink-soft);
  margin: 0;
}
.masthead { border-bottom: 3px double var(--rule); padding-bottom: 22px; margin-bottom: 30px; }
h1 { font-size: clamp(38px, 7vw, 58px); line-height: 1; margin: 14px 0 10px; font-weight: 600; letter-spacing: -.02em; }
.dek { margin: 0; color: var(--ink-soft); font-size: 16px; max-width: 46ch; font-style: italic; }
.card {
  background: #fffdf7;
  border: 1px solid var(--rule);
  border-radius: 3px;
  padding: 22px 24px;
  box-shadow: 0 1px 0 rgba(0,0,0,.03);
}
.card-head { display: flex; justify-content: space-between; gap: 12px; align-items: baseline; border-bottom: 1px solid var(--rule); padding-bottom: 10px; }
.label { font-family: ui-sans-serif, system-ui, sans-serif; font-size: 10.5px; letter-spacing: .16em; text-transform: uppercase; color: var(--ink-soft); }
.numbers { display: flex; gap: 8px; margin: 18px 0 6px; flex-wrap: wrap; }
.big { flex: 1 1 130px; }
.big .value { display: block; font-size: clamp(40px, 8vw, 54px); line-height: 1; font-variant-numeric: tabular-nums; letter-spacing: -.03em; }
.big.high .value { color: var(--brick); }
.big.low .value { color: var(--sky); }
.big .sub { display: block; margin-top: 6px; font-family: ui-sans-serif, system-ui, sans-serif; font-size: 11px; letter-spacing: .12em; text-transform: uppercase; color: var(--ink-soft); }
.compare { margin: 16px 0 0; font-size: 14.5px; color: var(--ink-soft); border-top: 1px dashed var(--rule); padding-top: 12px; }
.note { margin: 34px 0 0; }
.note h2 { font-size: clamp(24px, 4vw, 31px); line-height: 1.15; margin: 0 0 12px; font-weight: 600; letter-spacing: -.01em; }
.note p { margin: 0 0 14px; font-size: 17px; }
.byline { font-family: ui-sans-serif, system-ui, sans-serif; font-size: 11px; letter-spacing: .1em; text-transform: uppercase; color: var(--ink-soft); }
.facts { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 1px; background: var(--rule); border: 1px solid var(--rule); margin: 34px 0 0; }
.fact { background: var(--paper); padding: 14px 16px; }
.fact .k { font-family: ui-sans-serif, system-ui, sans-serif; font-size: 10px; letter-spacing: .14em; text-transform: uppercase; color: var(--ink-soft); }
.fact .v { font-size: 17px; margin-top: 4px; font-variant-numeric: tabular-nums; }
h3.section { font-family: ui-sans-serif, system-ui, sans-serif; font-size: 11px; letter-spacing: .18em; text-transform: uppercase; color: var(--ink-soft); margin: 44px 0 10px; font-weight: 600; }
table { width: 100%; border-collapse: collapse; font-size: 15px; font-variant-numeric: tabular-nums; }
th, td { text-align: left; padding: 9px 8px; border-bottom: 1px solid var(--rule); }
th { font-family: ui-sans-serif, system-ui, sans-serif; font-size: 10px; letter-spacing: .12em; text-transform: uppercase; color: var(--ink-soft); font-weight: 600; }
td.num, th.num { text-align: right; }
tr.best td { color: var(--green); font-weight: 600; }
td.day { font-family: ui-sans-serif, system-ui, sans-serif; font-size: 12.5px; color: var(--ink-soft); }
tr.today td { background: rgba(31,92,74,.07); }
.caption { font-size: 13px; color: var(--ink-soft); margin: 8px 0 0; font-style: italic; }
.chart { margin: 8px 0 0; }
.chart svg { width: 100%; height: auto; display: block; }
.method { font-size: 14.5px; color: var(--ink-soft); }
.method p { margin: 0 0 10px; }
.method strong { color: var(--ink); font-weight: 600; }
footer { margin-top: 44px; border-top: 1px solid var(--rule); padding-top: 16px; font-family: ui-sans-serif, system-ui, sans-serif; font-size: 11.5px; color: var(--ink-soft); line-height: 1.7; }
footer a { color: var(--green); }
.badge { display: inline-block; border: 1px solid var(--rule); border-radius: 2px; padding: 2px 7px; font-size: 10px; letter-spacing: .1em; text-transform: uppercase; color: var(--ink-soft); }
@media (max-width: 520px) {
  .wrap { padding: 26px 16px 50px; }
  .numbers { gap: 18px; }
  .big { flex-basis: 90px; }
}
"""


def _esc(value) -> str:
    return html.escape(str(value))


def _temp(value) -> str:
    if value is None:
        return "—"
    return f"{round(float(value))}°"


def _percent(value) -> str:
    if value is None:
        return "—"
    return f"{round(float(value) * 100)}%"


def _human_safe(value: str) -> str:
    try:
        day = dt.date.fromisoformat(value)
    except (TypeError, ValueError):
        return value
    return f"{day.strftime('%A')}, {day.strftime('%B')} {day.day}, {day.year}"


def _short_date(value: str) -> str:
    try:
        day = dt.date.fromisoformat(value)
    except (TypeError, ValueError):
        return value
    return f"{day.strftime('%b')} {day.day}"


def _chart(days: list[dict]) -> str:
    if len(days) < 5:
        return '<p class="caption">The chart fills in once a few days of observations are available.</p>'

    width, height = 740, 210
    left, right, top, bottom = 40, 12, 14, 26
    highs = [day["tmax"] for day in days]
    lows = [day["tmin"] for day in days]
    low_edge = min(lows) - 3
    high_edge = max(highs) + 3
    span = max(high_edge - low_edge, 12)

    def x(index: int) -> float:
        step = (width - left - right) / max(len(days) - 1, 1)
        return left + index * step

    def y(value: float) -> float:
        return top + (high_edge - value) / span * (height - top - bottom)

    band = (
        " ".join(f"{x(i):.1f},{y(day['tmax']):.1f}" for i, day in enumerate(days))
        + " "
        + " ".join(f"{x(i):.1f},{y(day['tmin']):.1f}" for i, day in reversed(list(enumerate(days))))
    )

    grid = []
    for step in range(4):
        value = low_edge + span * step / 3
        grid.append(
            f'<line x1="{left}" y1="{y(value):.1f}" x2="{width - right}" y2="{y(value):.1f}" '
            'stroke="#e2dac7" stroke-width="1" />'
            f'<text x="{left - 8}" y="{y(value) + 3.5:.1f}" text-anchor="end" font-size="9" '
            f'fill="#8b8371" font-family="ui-sans-serif, system-ui, sans-serif">{round(value)}</text>'
        )

    predicted = []
    for index, day in enumerate(days):
        if day.get("predicted_tmax") is not None:
            predicted.append(f"{x(index):.1f},{y(day['predicted_tmax']):.1f}")
    prediction_layer = ""
    if len(predicted) >= 2:
        prediction_layer = (
            f'<polyline points="{" ".join(predicted)}" fill="none" stroke="#1f5c4a" '
            'stroke-width="1.6" stroke-dasharray="4 3" />'
        ) + "".join(
            f'<circle cx="{point.split(",")[0]}" cy="{point.split(",")[1]}" r="2.4" fill="#1f5c4a" />'
            for point in predicted
        )

    first = _short_date(days[0]["date"])
    last = _short_date(days[-1]["date"])
    legend = (
        '<div style="display:flex;gap:16px;font-family:ui-sans-serif,system-ui,sans-serif;'
        'font-size:10.5px;letter-spacing:.08em;text-transform:uppercase;color:#5b5548;margin:2px 0 8px">'
        '<span style="color:#3c6e9c">— observed range</span>'
    )
    if len(predicted) >= 2:
        legend += '<span style="color:#1f5c4a">-- model high</span>'
    legend += "</div>"

    return (
        f'<div class="chart">{legend}'
        f'<svg viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="Daily high and low temperatures from {_esc(first)} to {_esc(last)}">'
        + "".join(grid)
        + f'<polygon points="{band}" fill="rgba(60,110,156,.14)" stroke="rgba(60,110,156,.5)" stroke-width="1" />'
        + prediction_layer
        + f'<text x="{left}" y="{height - 6}" font-size="9.5" fill="#8b8371" '
        f'font-family="ui-sans-serif, system-ui, sans-serif">{_esc(first)}</text>'
        + f'<text x="{width - right}" y="{height - 6}" text-anchor="end" font-size="9.5" fill="#8b8371" '
        f'font-family="ui-sans-serif, system-ui, sans-serif">{_esc(last)}</text>'
        "</svg></div>"
    )


def _skill_table(skill: dict) -> str:
    high, low, rain = skill["high"], skill["low"], skill["rain"]

    def best(row: dict, keys: tuple[str, ...]) -> str:
        winner = min(keys, key=lambda key: row[key])
        return winner

    high_best = best({"model": high["model"], "persistence": high["persistence"],
                      "climatology": high["climatology"]}, ("model", "persistence", "climatology"))
    low_best = best({"model": low["model"], "persistence": low["persistence"],
                     "climatology": low["climatology"]}, ("model", "persistence", "climatology"))

    def row(label: str, model: float, persistence: float, climatology: float, winner: str, suffix: str) -> str:
        cells = []
        for key, value in (("model", model), ("persistence", persistence), ("climatology", climatology)):
            css = ' class="num best"' if key == winner else ' class="num"'
            cells.append(f"<td{css}>{value:.2f}{suffix}</td>")
        return f"<tr><td>{_esc(label)}</td>{''.join(cells)}</tr>"

    rain_css = ' class="num best"' if rain["brier"] <= rain["brier_climatology"] else ' class="num"'

    return (
        "<table>"
        "<thead><tr><th>Scored on the last "
        f"{skill['days']} days</th><th class=\"num\">This model</th>"
        "<th class=\"num\">Yesterday repeats</th><th class=\"num\">Normal for the date</th></tr></thead><tbody>"
        + row("High temperature", high["model"], high["persistence"], high["climatology"], high_best, "°")
        + row("Low temperature", low["model"], low["persistence"], low["climatology"], low_best, "°")
        + f"<tr><td>Rain (Brier, lower is better)</td><td{rain_css}>{rain['brier']:.3f}</td>"
        + f"<td class=\"num\">—</td><td class=\"num\">{rain['brier_climatology']:.3f}</td></tr>"
        "</tbody></table>"
        f"<p class=\"caption\">Mean absolute error in °F. The model is retrained for every day in the "
        f"window using only what was known that morning. Rain occurred on "
        f"{round(rain['base_rate'] * 100)}% of those days.</p>"
    )


def _week_table(rows: list[dict]) -> str:
    body = []
    for row in rows:
        css = ' class="today"' if row.get("is_prediction") else ""
        rain = "—" if row.get("precip") is None else f"{row['precip']:.2f} in"
        body.append(
            f"<tr{css}><td class=\"day\">{_esc(row['label'])}</td>"
            f"<td class=\"num\">{_temp(row['tmax'])}</td>"
            f"<td class=\"num\">{_temp(row['tmin'])}</td>"
            f"<td class=\"num\">{rain}</td></tr>"
        )
    return (
        "<table><thead><tr><th>Day</th><th class=\"num\">High</th>"
        "<th class=\"num\">Low</th><th class=\"num\">Rain</th></tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table>"
    )


def render(state: dict) -> str:
    prediction = state["prediction"]
    skill = state["skill"]
    note = state["narrative"]
    official = state.get("official")
    live = state.get("live") or {}

    compare_bits = []
    if prediction.get("normal_tmax") is not None:
        compare_bits.append(
            f"Normal for the date is {_temp(prediction['normal_tmax'])} / "
            f"{_temp(prediction['normal_tmin'])}."
        )
    if official:
        compare_bits.append(
            f"Open-Meteo's own forecast: {_temp(official.get('tmax'))} / {_temp(official.get('tmin'))}."
        )

    facts = "".join(
        f'<div class="fact"><div class="k">{_esc(fact["label"])}</div>'
        f'<div class="v">{_esc(fact["value"])}</div></div>'
        for fact in state.get("facts", [])
    )

    live_line = ""
    if live.get("count", 0) >= 5:
        live_line = (
            f'<p class="caption">Live scoreboard: {live["count"]} daily calls published, '
            f'high off by {live["high_mae"]:.1f}° on average, low by {live["low_mae"]:.1f}°, '
            f'rain Brier {live["brier"]:.3f}.</p>'
        )

    paragraphs = "".join(
        f"<p>{_esc(part.strip())}</p>"
        for part in str(note["body"]).split("\n\n")
        if part.strip()
    )

    source_line = (
        f"Note by <strong>{_esc(note['model'])}</strong> via z.ai · numbers by the pattern model"
        if note.get("source") == "z.ai"
        else "Note from the built-in template · numbers by the pattern model"
    )

    backcast_note = ""
    if state.get("backcast_days", 0) > 0:
        backcast_note = (
            f'<p class="caption">The station record ran {state["backcast_days"]} day(s) behind, '
            'so this is the forecast for the first day not yet observed.</p>'
        )

    weather_rows = _week_table(state["week"])
    chart = _chart(state.get("days", []))
    skill_table = _skill_table(skill)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>The Charlotte Almanac · {_esc(_human_safe(state['target_date']))}</title>
<meta name="description" content="A daily Charlotte weather note, learned from decades of Piedmont records and scored against itself.">
<style>{CSS}</style>
</head>
<body>
<div class="wrap">
  <header class="masthead">
    <p class="eyebrow">Charlotte, North Carolina · 35.23°N, 80.84°W</p>
    <h1>The Charlotte Almanac</h1>
    <p class="dek">One paragraph a day about Piedmont weather, learned from eight decades of records
    and scored against itself in public.</p>
  </header>

  <section class="card">
    <div class="card-head">
      <span class="label">Forecast for</span>
      <span class="label">{_esc(_human_safe(state['target_date']))}</span>
    </div>
    <div class="numbers">
      <div class="big high"><span class="value">{_temp(prediction['tmax'])}</span><span class="sub">High</span></div>
      <div class="big low"><span class="value">{_temp(prediction['tmin'])}</span><span class="sub">Low</span></div>
      <div class="big"><span class="value">{_percent(prediction['pop'])}</span><span class="sub">Chance of rain</span></div>
    </div>
    <p class="compare">{' '.join(compare_bits)}{f" Expected rain {prediction['precip_in']:.2f} in." if prediction['pop'] >= 0.15 else ""}</p>
    {backcast_note}
  </section>

  <section class="note">
    <h2>{_esc(note['headline'])}</h2>
    {paragraphs}
    <p class="byline">{source_line}</p>
  </section>

  <div class="facts">{facts}</div>

  <h3 class="section">How the model is doing</h3>
  {skill_table}
  {live_line}

  <h3 class="section">The last thirty days</h3>
  {chart}

  <h3 class="section">The week</h3>
  {weather_rows}

  <h3 class="section">How this is made</h3>
  <div class="method">
    <p><strong>Data.</strong> NOAA's GHCN-Daily station record for Charlotte Douglas
    (USW00013881), which runs from 1939 to now, with Open-Meteo filling the last few days
    before the station record catches up and supplying the forward forecast used for
    comparison. The air upwind comes from the hourly airport records at Atlanta, Greer,
    Columbia and Asheville, by way of the Iowa Environmental Mesonet. All of it is free
    and keyless.</p>
    <p><strong>The pattern model.</strong> Daily features — yesterday's high, low and rain, lags out
    to two weeks, how far the last few days sat from normal, the wet-ground signal, the position
    of the year, the overnight air mass upwind and the day-ahead forecast high and low — fed to
    ridge regression for temperatures and
    logistic regression for rain. It retrains every morning on everything before today and
    predicts today.</p>
    <p><strong>The writer.</strong> A free z.ai GLM model turns the numbers into the note above. It is
    given the figures and told not to invent any; every number on this page comes from the
    statistical model or the weather archive, never from the language model.</p>
    <p><strong>The rules.</strong> The code that scores the model is the same code that produces the
    forecast, so the backtest cannot cheat: on each day it sees only what was known that morning.
    Predictions are logged before they resolve and scored afterwards.</p>
  </div>

  <footer>
    <p>Built {_esc(state['generated_label'])}. Observations end {_esc(_human_safe(state['latest_observation']))}.
    This is a personal notebook, not an official forecast — for decisions, use the
    <a href="https://www.weather.gov/gsp/">National Weather Service</a>.</p>
    <p>Observations: <a href="https://www.ncei.noaa.gov/products/land-based-station/global-historical-climatology-network-daily">NOAA GHCN-Daily</a>
    (public domain) · recent days and forecast: <a href="https://open-meteo.com/">Open-Meteo</a>
    (CC BY 4.0, ERA5 and ECMWF IFS day-ahead runs). Model {_esc(state['model_version'])} · updated daily by GitHub Actions.</p>
  </footer>
</div>
</body>
</html>
"""
