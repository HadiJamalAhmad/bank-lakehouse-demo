"""Position aggregation, ported from the legacy C# job (legacy/PositionAggregator).

    python -m bank_lakehouse.jobs.positions data/raw/trades.csv data/raw/fx_rates.csv out.csv

Same business rules as the C# job, in PySpark:
  1. latest version of each trade only;  2. cancelled trades dropped;
  3. notional in CHF with the FX rate of the trade date or the most recent earlier one
     (CHF = 1, no rate at all is an error);  4. each notional rounded to 2 decimals;
  5. per (counterparty, instrument): net quantity, gross CHF notional, trade count.
"""

import csv
import sys
from decimal import Decimal

from pyspark.sql import DataFrame, SparkSession, Window
from pyspark.sql import functions as F
from pyspark.sql import types as T

TRADES = T.StructType([
    T.StructField("trade_id", T.StringType(), False),
    T.StructField("version", T.IntegerType(), False),
    T.StructField("trade_date", T.DateType(), False),
    T.StructField("counterparty_id", T.StringType(), False),
    T.StructField("instrument_id", T.StringType(), False),
    T.StructField("side", T.StringType(), False),
    T.StructField("quantity", T.LongType(), False),
    T.StructField("price", T.DecimalType(12, 3), False),
    T.StructField("currency", T.StringType(), False),
    T.StructField("status", T.StringType(), False),
])
FX = T.StructType([
    T.StructField("currency", T.StringType(), False),
    T.StructField("rate_date", T.DateType(), False),
    T.StructField("rate_to_chf", T.DecimalType(12, 6), False),
])


def read_csv(spark: SparkSession, path: str, schema: T.StructType) -> DataFrame:
    return spark.read.csv(path, header=True, schema=schema, mode="FAILFAST")


def latest_active(trades: DataFrame) -> DataFrame:
    w = Window.partitionBy("trade_id").orderBy(F.col("version").desc())
    return (trades.withColumn("_rn", F.row_number().over(w))
            .where("_rn = 1").drop("_rn")
            .where(F.col("status") != "CANCELLED"))


def with_rate(trades: DataFrame, fx: DataFrame) -> DataFrame:
    """As-of join: the rate of the trade date, or the most recent earlier one."""
    t = trades.alias("t")
    r = fx.alias("r")
    joined = t.join(r, (F.col("t.currency") == F.col("r.currency"))
                    & (F.col("r.rate_date") <= F.col("t.trade_date")), "left")
    w = Window.partitionBy("t.trade_id").orderBy(F.col("r.rate_date").desc_nulls_last())
    best = (joined.withColumn("_rn", F.row_number().over(w)).where("_rn = 1")
            .select("t.*", F.col("r.rate_to_chf")))
    rate = F.when(F.col("currency") == "CHF", F.lit(1).cast(T.DecimalType(12, 6))) \
        .otherwise(F.col("rate_to_chf"))
    return best.withColumn("rate", rate).drop("rate_to_chf")


def positions(trades: DataFrame, fx: DataFrame) -> DataFrame:
    priced = with_rate(latest_active(trades), fx)
    missing = priced.where(F.col("rate").isNull()).select("trade_id", "currency", "trade_date")
    if missing.limit(1).count():
        row = missing.first()
        raise ValueError(f"no FX rate for {row.currency} on or before {row.trade_date} "
                         f"(trade {row.trade_id})")
    notional = (F.col("quantity").cast(T.DecimalType(12, 0)) * F.col("price") * F.col("rate"))
    signed = F.when(F.col("side") == "BUY", F.col("quantity")).otherwise(-F.col("quantity"))
    return (priced.withColumn("notional_chf", F.round(notional, 2))
            .groupBy("counterparty_id", "instrument_id")
            .agg(F.sum(signed).alias("net_quantity"),
                 F.sum("notional_chf").alias("gross_notional_chf"),
                 F.count("*").alias("trade_count"))
            .orderBy("counterparty_id", "instrument_id"))


def write_csv(df: DataFrame, path: str) -> int:
    """Small result: collected on the driver and written exactly like the legacy job."""
    rows = df.collect()
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["counterparty_id", "instrument_id", "net_quantity", "gross_notional_chf",
                    "trade_count"])
        for r in rows:
            w.writerow([r.counterparty_id, r.instrument_id, r.net_quantity,
                        f"{Decimal(r.gross_notional_chf):.2f}", r.trade_count])
    return len(rows)


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: positions <trades.csv> <fx_rates.csv> <positions.csv>", file=sys.stderr)
        return 2
    from bank_lakehouse.spark import session

    spark = session("positions")
    try:
        n = write_csv(positions(read_csv(spark, argv[0], TRADES),
                                read_csv(spark, argv[1], FX)), argv[2])
    finally:
        spark.stop()
    print(f"{n} positions written to {argv[2]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
