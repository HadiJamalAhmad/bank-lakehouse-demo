"""Parity check: the legacy output and the migrated output must be identical, row by row.

    python tools/parity.py legacy.csv migrated.csv

Compares on the business key (counterparty_id, instrument_id); numbers are compared as exact
decimals, not floats. Exit code 0 only when there are zero differences.
"""

import csv
import sys
from decimal import Decimal

KEY = ("counterparty_id", "instrument_id")
NUMERIC = {"net_quantity", "gross_notional_chf", "trade_count"}


def load(path: str) -> tuple[list[str], dict[tuple, dict]]:
    with open(path, newline="") as fh:
        reader = csv.DictReader(fh)
        rows = {}
        for r in reader:
            k = tuple(r[c] for c in KEY)
            if k in rows:
                raise SystemExit(f"{path}: duplicate key {k}")
            rows[k] = {c: (Decimal(v) if c in NUMERIC else v) for c, v in r.items()}
        return list(reader.fieldnames or []), rows


def compare(a_path: str, b_path: str) -> list[str]:
    a_cols, a = load(a_path)
    b_cols, b = load(b_path)
    diffs = []
    if a_cols != b_cols:
        diffs.append(f"columns differ: {a_cols} vs {b_cols}")
    for k in sorted(a.keys() - b.keys()):
        diffs.append(f"{k}: only in legacy")
    for k in sorted(b.keys() - a.keys()):
        diffs.append(f"{k}: only in migrated")
    for k in sorted(a.keys() & b.keys()):
        for c in a_cols:
            if c in b[k] and a[k][c] != b[k][c]:
                diffs.append(f"{k} {c}: legacy={a[k][c]} migrated={b[k][c]}")
    return diffs


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: parity.py <legacy.csv> <migrated.csv>", file=sys.stderr)
        return 2
    _, a = load(argv[0])
    diffs = compare(*argv)
    print(f"rows compared: {len(a)}")
    if diffs:
        print(f"DIFFERENCES: {len(diffs)}")
        for d in diffs[:15]:
            print("  " + d)
        if len(diffs) > 15:
            print(f"  ... and {len(diffs) - 15} more")
        return 1
    print("PARITY OK: 0 differences")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
