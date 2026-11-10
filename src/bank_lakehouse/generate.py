"""Deterministic synthetic trade data: realistic enough to exercise every business rule.

    python -m bank_lakehouse.generate data/raw --trades 20000

Writes trades.csv (with amendments and cancellations) and fx_rates.csv (business days only,
so weekend trades must fall back to the previous rate). Prices have 3 decimals, so many CHF
notionals end on an exact half cent: the rounding rule matters.
"""

import argparse
import csv
import random
from datetime import date, timedelta
from pathlib import Path

CURRENCIES = {"CHF": None, "EUR": 0.94, "USD": 0.88, "GBP": 1.12}
START = date(2026, 1, 1)
DAYS = 120


def business_days():
    d = START - timedelta(days=7)  # rates start a week before the first trade
    while d < START + timedelta(days=DAYS):
        if d.weekday() < 5:
            yield d
        d += timedelta(days=1)


def generate(out: Path, n_trades: int, seed: int = 7) -> None:
    rng = random.Random(seed)
    out.mkdir(parents=True, exist_ok=True)

    with open(out / "fx_rates.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["currency", "rate_date", "rate_to_chf"])
        for ccy, base in CURRENCIES.items():
            if base is None:
                continue
            rate = base
            for d in business_days():
                rate *= 1 + rng.gauss(0, 0.003)
                w.writerow([ccy, d.isoformat(), f"{rate:.6f}"])

    cptys = [f"CP{i:03d}" for i in range(1, 41)]
    instruments = [f"ISIN{i:04d}" for i in range(1, 61)]
    with open(out / "trades.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["trade_id", "version", "trade_date", "counterparty_id", "instrument_id",
                    "side", "quantity", "price", "currency", "status"])
        for i in range(1, n_trades + 1):
            row = {
                "trade_id": f"T{i:07d}",
                "trade_date": (START + timedelta(days=rng.randrange(DAYS))).isoformat(),
                "counterparty_id": rng.choice(cptys),
                "instrument_id": rng.choice(instruments),
                "side": rng.choice(["BUY", "SELL"]),
                "quantity": rng.choice([1, 5, 10, 25, 50, 100, 250, 1000]) * rng.randint(1, 9),
                "price": f"{rng.uniform(5, 500):.3f}",
                "currency": rng.choices(list(CURRENCIES), weights=[5, 3, 3, 1])[0],
            }
            versions = [dict(row, version=1, status="NEW")]
            r = rng.random()
            if r < 0.15:  # amended once or twice
                for v in range(2, rng.randint(2, 3) + 1):
                    amended = dict(versions[-1], version=v, status="AMENDED")
                    amended["quantity"] = max(1, int(amended["quantity"] * rng.uniform(0.5, 1.5)))
                    versions.append(amended)
            elif r < 0.20:  # cancelled
                versions.append(dict(row, version=2, status="CANCELLED"))
            rng.shuffle(versions)  # the source system does not guarantee order
            for v in versions:
                w.writerow([v["trade_id"], v["version"], v["trade_date"], v["counterparty_id"],
                            v["instrument_id"], v["side"], v["quantity"], v["price"],
                            v["currency"], v["status"]])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out", type=Path)
    ap.add_argument("--trades", type=int, default=20000)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    generate(a.out, a.trades, a.seed)
    print(f"wrote {a.out / 'trades.csv'} and {a.out / 'fx_rates.csv'}")


if __name__ == "__main__":
    main()
