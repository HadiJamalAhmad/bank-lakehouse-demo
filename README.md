# bank-lakehouse-demo

[![ci](https://github.com/HadiJamalAhmad/bank-lakehouse-demo/actions/workflows/ci.yml/badge.svg)](https://github.com/HadiJamalAhmad/bank-lakehouse-demo/actions/workflows/ci.yml)

Results page: https://bank-lakehouse-demo.vercel.app

A bank lakehouse in miniature: PySpark pipelines on trade data, and a C# to Python migration
proven by a row-by-row parity test.

## Step 1 (done): migrate a legacy C# job to PySpark, and prove nothing changed

`legacy/PositionAggregator` is a C# position-aggregation job, the kind a bank wants to retire:
latest version of each trade, cancelled trades dropped, notional converted to CHF with the
FX rate of the trade date (or the previous business day), rounded to the cent, aggregated per
counterparty and instrument.

`src/bank_lakehouse/jobs/positions.py` is the PySpark port. `tools/parity.py` compares both
outputs on the business key, with exact decimals.

What the parity test caught: the first port was off by one cent on **308 of 2,399 positions**.
C# `Math.Round(decimal, 2)` rounds half to even (banker's rounding); Spark `round()` rounds
half up. Switching to `bround()` gives **0 differences** (see the git history).

```bash
uv sync --extra dev
uv run python -m bank_lakehouse.generate data/raw --trades 20000
dotnet run -c Release --project legacy/PositionAggregator -- data/raw/trades.csv data/raw/fx_rates.csv out/legacy_positions.csv
uv run python -m bank_lakehouse.jobs.positions data/raw/trades.csv data/raw/fx_rates.csv out/migrated_positions.csv
uv run python tools/parity.py out/legacy_positions.csv out/migrated_positions.csv
uv run pytest -q   # business rules + end-to-end parity (needs the .NET 8 SDK)
```

Data is synthetic and deterministic (`generate.py`): amendments, cancellations, events out of
order, weekend trades, prices with 3 decimals so half cents really occur.

## Next steps

2. Lakehouse layers on Apache Iceberg tables: raw, cleaned, business (time travel included).
3. Data model: trade fact, instrument / counterparty / date dimensions; exposure by counterparty in SQL.
4. Orchestration and data quality: an Airflow DAG; a failing quality check stops the load.
5. On-call drill: an alert, root cause in the logs, targeted rerun, short post-mortem.
6. ~~CI/CD: GitHub Actions running lint, tests and the parity test.~~ Done: `.github/workflows/ci.yml`,
   which installs the .NET SDK and fails the run if the parity test is skipped.

## Results page

`site/index.html` is a static page with the real parity outputs (before and after the fix),
deployed on Vercel from the `site/` folder: https://bank-lakehouse-demo.vercel.app
