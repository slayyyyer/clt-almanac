# The Charlotte Almanac

A daily weather notebook for Charlotte, North Carolina. Every morning a GitHub
Action pulls the weather record, retrains a small model on it, predicts the day,
asks a free z.ai model to write the paragraph, and publishes the result to GitHub
Pages. The model is scored in public against two baselines, and every prediction
is logged before it resolves.

New here? [**How it works**](docs/how-it-works.md) walks through the whole loop
with diagrams — sources, features, models and scoring. The measured results are
in the [experiments log](docs/experiments.md), and
[the baseline record](docs/baseline_metrics.md) shows what it improved on.

## Does the data exist?

Yes, and it is free and keyless.

**History:** NOAA's [GHCN-Daily](https://www.ncei.noaa.gov/products/land-based-station/global-historical-climatology-network-daily)
record for Charlotte Douglas International Airport, station `USW00013881`. One CSV
of daily highs, lows and precipitation running from **1939 to a few days ago**, in
the public domain and without a key.

**The last few days and the days ahead:** [Open-Meteo](https://open-meteo.com/).
Its forecast endpoint fills the gap while the station record catches up (GHCN
usually runs two to four days behind) and supplies the independent forecast the
page compares against. Its archive is the fallback if NCEI is unreachable.

**The air on its way:** the [Iowa Environmental Mesonet](https://mesonet.agron.iastate.edu/)
keeps the hourly ASOS records from Atlanta, Greer, Columbia and Asheville. Their
mean temperature between 00Z and 05Z is an estimate of the regional air mass
Charlotte is about to receive — not a forecast, but not local history either.

**What the models expected:** Open-Meteo's
[previous-runs API](https://open-meteo.com/en/docs/previous-runs-api) keeps each
forecast at fixed lead times, so `temperature_2m_previous_day1` is the value ECMWF
predicted 24 hours before it verified — available by construction at the 07:17Z
press time. The archive starts in June 2024, which is why the model now trains on
that era instead of twenty years of station history.

Charlotte is at 35.2271°N, 80.8431°W. The station sits at the airport, about eight
miles west of uptown.

## Who does what

Three separate pieces, deliberately:

1. **The pattern model** (`src/learn.py`, `src/models.py`) produces every number.
   Daily features — yesterday's high, low and rain, lags out to two weeks, rolling
   means, anomalies against normal, the wet-ground signal, the position of the
   year, the overnight air mass upwind and the day-ahead forecast — go into ridge
   regression for the high and low, and L2 logistic regression for the chance of
   rain. It retrains on everything before today and
   predicts today.
2. **The narrator** (`src/narrative.py`) is `glm-4.7-flash` on z.ai's free tier.
   It receives the finished numbers and writes 70–110 words of prose. It is
   explicitly told not to invent figures, and if the key is missing or the call
   fails, a built-in template writes the note and the page says so.
3. **The page** (`src/site.py`) is one static HTML file with inline CSS and a
   hand-drawn SVG chart. No JavaScript, no external assets, no build step.

Numbers come from the statistical model. Language models are fluent but not
arithmetically reliable, so letting one emit a forecast would mean publishing
guesses. Instead it does the part it is genuinely good at.

## Why the backtest is trustworthy

The walk-forward test at the bottom of the page retrains the model for every one
of the last 365 days, using only the rows that existed that morning, and then
scores the result. The feature builder that produces the backtest rows is the
same function that produces the live forecast, so the backtest cannot quietly
see tomorrow. Three numbers are reported for the high and low:

- **This model** — ridge regression on the features above
- **Yesterday repeats** — persistence, a strong and honest baseline
- **Normal for the date** — the smoothed 1991–2020 climatology

Rain is scored with the Brier score against the climatological base rate. On top
of that, `data/predictions.jsonl` records each forecast the day it is issued, so
once a few weeks have accumulated the page also shows a live scoreboard of calls
made before the outcome existed.
Each target date is logged once, when it is issued; a rerun later the same day cannot
rewrite it, and a day the record has already reached is not logged at all.

## Run it locally

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # Windows
# source .venv/bin/activate && pip install -r requirements.txt   # macOS / Linux

python -m src.main --no-narrative        # skip z.ai, use the template note
python -m src.main                       # needs ZAI_API_KEY in the environment
```

`--days 90` narrows the backtest window (handy while iterating), and
`--refresh-normals` refetches the 1991–2020 climate normals. The first run also
backfills `data/upstream.json` from the Mesonet (about 20 MB of hourly records);
later runs only ask for the days past the cached edge, and the workflow commits
the file so the archive travels with the repository. `data/nwp.json` caches the
day-ahead forecasts the same way, fetched in 180-day chunks the first time.

Output lands in `public/index.html` and `public/forecast.json`. Open the HTML
file directly; it has no dependencies.

Run the regression tests with `python -m unittest discover -s tests -t .` —
standard library only, no network.

## Put it on GitHub Pages

1. Create a repository and push this folder to it.
2. Get a free API key at <https://z.ai> → API Keys, then add it under
   **Settings → Secrets and variables → Actions → New repository secret** as
   `ZAI_API_KEY`. Optional: set a repository *variable* `ZAI_MODEL` if you want a
   different model than `glm-4.7-flash`.
3. **Settings → Pages → Build and deployment → Source: GitHub Actions.**
4. Run the **Daily Charlotte forecast** workflow once from the Actions tab.

The schedule is `17 7 * * *` UTC, about 3:17am in Charlotte in summer and 2:17am
in winter — before the day being predicted has happened. GitHub may delay
scheduled runs by a few minutes under load.

Each run commits the updated `data/predictions.jsonl` back to the repository so
the prediction log survives between runs; that is why the workflow asks for
`contents: write`.

## Cost

Zero. Open-Meteo is free for non-commercial use, the Mesonet archive is free and
needs no key, and `glm-4.7-flash` is one of z.ai's free models. One z.ai request
per day, roughly 600 tokens in and 300 out.

## Limits worth knowing

- The model is linear on twenty-six features. It will not see a stalled front, a
  tropical system, or cold-air damming better than persistence does — the skill
  table is there to say so honestly.
- The upwind airports are a proxy for a single air mass, not a trajectory. On a
  day when the wind backs around, they can describe the wrong air entirely, and
  the average over four stations hides that.
- Daily values are for one grid cell near uptown Charlotte. The airport, Matthews
  and Lake Norman will differ.
- GHCN runs two to four days behind, so the newest days of "observed" weather
  come from Open-Meteo's analysis rather than the airport station. The two agree
  closely but are not the same measurement.
- The day-ahead archive starts in June 2024, so the model trains on about two and
  a half years of rows instead of twenty. That is the price of its strongest
  feature.
- ECMWF runs about 1.8°F cold on Charlotte's daily high. The ridge learns that
  offset; a change of model version would need it relearned.
- This is a notebook, not an official forecast. The National Weather Service is
  the authority for decisions.
