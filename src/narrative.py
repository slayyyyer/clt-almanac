"""The narrator: z.ai's free GLM model writes the daily note.

The language model never produces a forecast number. It receives the numbers the
statistical model already computed and turns them into a paragraph a person would
actually want to read. If the key is missing or the call fails, a plain template
takes over and the page says so.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

ENDPOINT = "https://api.z.ai/api/paas/v4/chat/completions"
DEFAULT_MODEL = "glm-4.7-flash"
MAX_TOKENS = 900

SYSTEM = (
    "You write the daily weather note for a small almanac in Charlotte, North Carolina. "
    "Your voice is warm, plain and observant, like a neighbour who has been through forty "
    "Piedmont summers. You never invent numbers, places or events. You use only the figures "
    "given to you, and you never mention models, algorithms or forecasts-of-forecasts."
)

INSTRUCTIONS = """\
Write exactly two things.

Headline: one line, nine words or fewer, no exclamation marks, no markdown, no period at the end.

Then the note: 70 to 110 words, in two short paragraphs. Say how the day sits against normal for
the date, what the last week has been doing, and whether rain is worth planning around. Pick the
one or two numbers that matter most; do not recite all of them. Temperatures are Fahrenheit and
rain is in inches. Do not add a sign-off, a greeting, or a list.
"""


def _prompt(context: dict) -> str:
    return (
        "Today's sheet, as JSON:\n\n"
        f"{json.dumps(context, indent=2)}\n\n"
        f"{INSTRUCTIONS}"
    )


def _post(payload: dict, api_key: str, timeout: int = 60) -> dict:
    request = urllib.request.Request(
        ENDPOINT,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "clt-almanac/1.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _split(text: str, fallback_headline: str) -> tuple[str, str]:
    cleaned = text.strip().replace("**", "")
    lines = [line.strip() for line in cleaned.splitlines()]
    headline = ""
    body_lines: list[str] = []
    for line in lines:
        lower = line.lower()
        if lower.startswith("headline:"):
            headline = line.split(":", 1)[1].strip().strip('"').strip("*")
            continue
        body_lines.append(line)
    body = "\n".join(body_lines).strip()
    if not headline:
        first = body_lines[0] if body_lines else ""
        if 0 < len(first.split()) <= 12:
            headline = first
            body = "\n".join(body_lines[1:]).strip()
        else:
            headline = fallback_headline
    return headline.rstrip("."), body


def _fallback(context: dict, reason: str = "") -> dict:
    high = context.get("predicted_high_f")
    low = context.get("predicted_low_f")
    normal_high = context.get("normal_high_f")
    normal_low = context.get("normal_low_f")
    pop = context.get("chance_of_rain_percent") or 0
    rain = context.get("expected_rain_inches") or 0.0
    week = context.get("seven_day_mean_high_f")

    delta = None if high is None or normal_high is None else round(high - normal_high)
    if delta is None:
        headline = "A day in the Piedmont"
    elif delta >= 7:
        headline = "Well above normal, and holding"
    elif delta >= 3:
        headline = "Warmer than the calendar suggests"
    elif delta <= -7:
        headline = "Cold air settles over the Piedmont"
    elif delta <= -3:
        headline = "Cooler than the calendar suggests"
    else:
        headline = "Close to normal for the date"

    opening: list[str] = []
    if None not in (high, low, normal_high, normal_low):
        relation = "about normal"
        if delta is not None:
            if delta > 0:
                relation = f"about {delta}° above the normal {round(normal_high)}°"
            elif delta < 0:
                relation = f"about {abs(delta)}° below the normal {round(normal_high)}°"
        opening.append(
            f"Today should top out near {high:.0f}° and drop to about {low:.0f}°, {relation} "
            f"for the date (normal low {round(normal_low)}°)."
        )
    if week is not None:
        opening.append(f"The past week has averaged {week:.0f}° at the high.")

    if pop >= 45:
        rain_note = (
            f"Rain is the main story: a {pop:.0f}% chance, with roughly {rain:.2f} in expected."
        )
    elif pop >= 20:
        rain_note = (
            f"There is a {pop:.0f}% chance of rain, so about {rain:.2f} in — worth knowing, "
            "not worth cancelling plans over."
        )
    else:
        rain_note = f"Rain stays unlikely at {pop:.0f}%; keep the umbrella where it is."

    return {
        "headline": headline,
        "body": " ".join(opening) + "\n\n" + rain_note,
        "source": "template",
        "model": None,
        "note": reason,
    }


def _payload(model: str, context: dict, disable_thinking: bool) -> dict:
    """GLM 4.x are hybrid reasoning models. Left on, thinking eats the whole token
    budget and the visible answer comes back empty or clipped; the note needs prose,
    not deliberation."""
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": _prompt(context)},
        ],
        "temperature": 0.65,
        "top_p": 0.9,
        "max_tokens": MAX_TOKENS,
    }
    if disable_thinking:
        payload["thinking"] = {"type": "disabled"}
    return payload


def _complete(model: str, context: dict, api_key: str) -> dict:
    """Older GLM builds reject the thinking switch, so fall back to a plain payload."""
    try:
        return _post(_payload(model, context, disable_thinking=True), api_key)
    except urllib.error.HTTPError as error:
        if error.code not in (400, 422):
            raise
        return _post(_payload(model, context, disable_thinking=False), api_key)


def write(context: dict, allow_api: bool = True) -> dict:
    api_key = os.environ.get("ZAI_API_KEY", "").strip()
    model = os.environ.get("ZAI_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
    fallback_headline = _fallback(context)["headline"]

    if not allow_api:
        return _fallback(context, reason="narrative disabled")
    if not api_key:
        return _fallback(context, reason="ZAI_API_KEY not set")

    try:
        response = _complete(model, context, api_key)
        choice = response["choices"][0]
        text = (choice.get("message", {}).get("content") or "").strip()
        headline, body = _split(text, fallback_headline)
        words = len(body.split())
        if words < 25:
            raise ValueError(
                f"completion too short: {words} words, finish_reason="
                f"{choice.get('finish_reason')}, {len(text)} chars"
            )
        return {"headline": headline, "body": body, "source": "z.ai", "model": model, "note": ""}
    except Exception as error:  # noqa: BLE001 - the page must still publish
        return _fallback(context, reason=f"{type(error).__name__}: {error}"[:160])
