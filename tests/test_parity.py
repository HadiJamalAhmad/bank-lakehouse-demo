"""End-to-end parity: the legacy C# job and the PySpark port give identical outputs."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOTNET = shutil.which("dotnet") or str(Path.home() / ".dotnet" / "dotnet.exe")
sys.path.insert(0, str(ROOT / "tools"))
from parity import compare  # noqa: E402


@pytest.mark.skipif(not Path(DOTNET).exists(), reason="needs the .NET SDK")
def test_legacy_and_migrated_outputs_are_identical(tmp_path):
    from bank_lakehouse.generate import generate
    from bank_lakehouse.jobs.positions import main as migrated

    generate(tmp_path, n_trades=3000, seed=11)
    trades, fx = str(tmp_path / "trades.csv"), str(tmp_path / "fx_rates.csv")
    legacy_out, new_out = tmp_path / "legacy.csv", tmp_path / "migrated.csv"
    subprocess.run([DOTNET, "run", "-c", "Release", "--project",
                    str(ROOT / "legacy" / "PositionAggregator"), "--", trades, fx,
                    str(legacy_out)], check=True)
    assert migrated([trades, fx, str(new_out)]) == 0
    assert compare(str(legacy_out), str(new_out)) == []
