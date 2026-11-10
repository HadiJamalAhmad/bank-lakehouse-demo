"""Business rules of the migrated job, each on a tiny hand-written case."""

import csv
import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from bank_lakehouse.jobs.positions import FX, TRADES, positions, read_csv

D = Decimal


@pytest.fixture(scope="module")
def spark():
    from bank_lakehouse.spark import session

    s = session("tests")
    yield s
    s.stop()


def trade(tid, version=1, day=date(2026, 1, 5), cpty="CP001", instr="ISIN0001", side="BUY",
          qty=10, price="100.000", ccy="CHF", status="NEW"):
    return (tid, version, day, cpty, instr, side, qty, D(price), ccy, status)


def run(spark, trades, fx=()):
    """Write the case to CSV and read it back through the job's real reader (no Python
    workers: Spark's in-memory createDataFrame crashes them on Windows)."""
    tmp = Path(tempfile.mkdtemp())
    for name, rows, schema in (("trades.csv", trades, TRADES), ("fx.csv", fx, FX)):
        with open(tmp / name, "w", newline="") as fh:
            w = csv.writer(fh, lineterminator="\n")
            w.writerow(schema.fieldNames())
            w.writerows(rows)
    df = positions(read_csv(spark, str(tmp / "trades.csv"), TRADES),
                   read_csv(spark, str(tmp / "fx.csv"), FX))
    return {(r.counterparty_id, r.instrument_id): r for r in df.collect()}


def test_latest_version_wins_whatever_the_order(spark):
    out = run(spark, [trade("T1", version=2, qty=30, status="AMENDED"), trade("T1", qty=10)])
    p = out[("CP001", "ISIN0001")]
    assert (p.net_quantity, p.trade_count) == (30, 1)


def test_cancelled_trades_are_dropped(spark):
    out = run(spark, [trade("T1"), trade("T1", version=2, status="CANCELLED"), trade("T2")])
    assert out[("CP001", "ISIN0001")].trade_count == 1


def test_sell_is_negative_and_gross_is_summed(spark):
    out = run(spark, [trade("T1", qty=10), trade("T2", side="SELL", qty=4)])
    p = out[("CP001", "ISIN0001")]
    assert p.net_quantity == 6
    assert p.gross_notional_chf == D("1400.00")


def test_weekend_trade_uses_the_previous_business_day_rate(spark):
    fx = [("EUR", date(2026, 1, 2), D("0.900000")), ("EUR", date(2026, 1, 5), D("0.950000"))]
    out = run(spark, [trade("T1", day=date(2026, 1, 4), ccy="EUR")], fx)  # Sunday
    assert out[("CP001", "ISIN0001")].gross_notional_chf == D("900.00")


def test_no_rate_at_all_is_an_error(spark):
    with pytest.raises(ValueError, match="no FX rate for USD"):
        run(spark, [trade("T1", ccy="USD")], [("USD", date(2026, 2, 1), D("0.9"))])


def test_half_cent_is_rounded_like_the_legacy_job(spark):
    # 1 x 0.125 CHF = 0.125: C# Math.Round(decimal, 2) gives 0.12 (banker's rounding)
    out = run(spark, [trade("T1", qty=1, price="0.125")])
    assert out[("CP001", "ISIN0001")].gross_notional_chf == D("0.12")
