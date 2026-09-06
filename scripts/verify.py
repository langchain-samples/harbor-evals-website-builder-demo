"""Run the verifier against known artifacts. No model, no sandbox, no cost.

The gate before you trust a change to the verifier: the recorded bad page must
fail for the right reason, and the reference solution must still reach 1.0. A
check nothing can pass is as broken as one nothing can fail.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHECK = ROOT / "dataset" / "halden-cycles-booking-form" / "tests" / "check.py"
SOLVE = ROOT / "dataset" / "halden-cycles-booking-form" / "solution" / "solve.sh"
REWARD = re.compile(r"^REWARD\s+([\d.]+)", re.M)


def score(site: Path, label: str) -> float | None:
    rewards = Path(tempfile.mkdtemp())
    print(f"\n{'=' * 66}\n  {label}\n{'=' * 66}", flush=True)
    out = subprocess.run(
        [sys.executable, str(CHECK), str(site)],
        capture_output=True, text=True,
        env={**__import__("os").environ, "REWARD_DIR": str(rewards)},
    )
    print(out.stdout[-1400:])
    m = REWARD.search(out.stdout)
    return float(m.group(1)) if m else None


def main() -> int:
    problems = []

    bad = ROOT / "demo-pages" / "halden-cycles-scored"
    if bad.is_dir():
        s = score(bad, "the recorded page the judge scored 1.00 (must be 0.0)")
        if s != 0.0:
            problems.append(f"recorded bad page scored {s}, expected 0.0")
    else:
        problems.append(f"missing {bad}")

    oracle = Path(tempfile.mkdtemp(prefix="oracle-"))
    shutil.rmtree(oracle)
    shutil.copytree(ROOT / "scaffold", oracle)
    subprocess.run(["bash", str(SOLVE)], check=True,
                   env={**__import__("os").environ, "SITE_DIR": str(oracle)},
                   capture_output=True)
    s = score(oracle, "the reference solution (must be 1.0)")
    if s != 1.0:
        problems.append(f"reference solution scored {s}, expected 1.0 — the task may be unpassable")

    print("\n" + "=" * 66)
    if problems:
        print("  PROBLEMS")
        for p in problems:
            print(f"    - {p}")
        return 1
    print("  The recorded page fails for the right reason and the reference")
    print("  solution reaches 1.0. The verifier is sound.")
    print("=" * 66)
    return 0


if __name__ == "__main__":
    sys.exit(main())
