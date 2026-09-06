"""Run every task's verifier against its own `solution/` and its start state.

An eval nobody can pass is a broken eval, and so is one that scores well for
doing nothing. This runs each verifier twice — once against the reference
solution, once against whatever the task starts from — and reports both
numbers.

    python evals/check_solutions.py

Expect 1.000 on every solution. The floor column is the score for changing
nothing, which is the useful sanity check on whether a task discriminates.

No Docker and no Harbor: this calls the verifiers directly, which is why they
fall back to their own directory when /tests does not exist.
"""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

EVALS = Path(__file__).parent
REWARD = re.compile(r"reward=([\d.]+)")


def score(task: Path, site: Path) -> float | None:
    result = subprocess.run(
        [sys.executable, str(task / "tests" / "test_site.py"), str(site)],
        capture_output=True,
        text=True,
    )
    match = REWARD.search(result.stdout)
    if not match:
        print(f"  !! {task.name}: verifier produced no reward\n{result.stdout}{result.stderr}")
        return None
    return float(match.group(1))


def main() -> int:
    tasks = sorted(p for p in EVALS.iterdir() if (p / "task.toml").is_file())
    empty = Path(tempfile.mkdtemp())
    failures = 0

    print(f"{'task':<22} {'floor':>7} {'solution':>9}")
    print("-" * 40)

    for task in tasks:
        solution = task / "solution"
        # A task either seeds a starting site or starts from nothing.
        seed = task / "environment" / "seed"
        start = seed if seed.is_dir() else empty

        floor = score(task, start)
        best = score(task, solution) if solution.is_dir() else None

        floor_txt = f"{floor:.3f}" if floor is not None else "—"
        best_txt = f"{best:.3f}" if best is not None else "no solution/"
        print(f"{task.name:<22} {floor_txt:>7} {best_txt:>9}")

        if best is None or best < 0.999:
            failures += 1
            print(f"  !! {task.name}: reference solution does not score 1.000")
        if floor is not None and best is not None and floor >= best:
            failures += 1
            print(f"  !! {task.name}: doing nothing scores as well as solving it")

    print()
    if failures:
        print(f"{failures} problem(s) found")
        return 1
    print(f"{len(tasks)} task(s) healthy")
    return 0


if __name__ == "__main__":
    sys.exit(main())
