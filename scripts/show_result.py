"""Print the most recent Harbor trial as the table you show on stage.

`harbor view` is the interactive way; this is the one-screen version, with
the failing check's own explanation next to it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

JOBS = Path("/tmp/harbor-jobs")
ORDER = ["renders", "brief_coverage", "controls_work", "validation_works", "responsive", "no_errors"]


def main() -> int:
    jobs = sorted((p for p in JOBS.glob("*/") if p.is_dir()), reverse=True)
    if not jobs:
        print(f"no jobs under {JOBS} — run `make harbor` first")
        return 1

    for job in jobs:
        trials = sorted(p for p in job.glob("*/") if (p / "verifier" / "reward.json").is_file())
        if not trials:
            continue
        print(f"job: {job.name}")
        for trial in trials:
            reward = json.loads((trial / "verifier" / "reward.json").read_text())
            notes_path = trial / "verifier" / "notes.json"
            notes = json.loads(notes_path.read_text()) if notes_path.is_file() else {}

            print(f"\n  {trial.name}\n")
            print(f"  {'check':<20} {'score':>6}   why")
            print("  " + "-" * 66)
            for key in ORDER:
                if key in reward:
                    print(f"  {key:<20} {reward[key]:>6.1f}   {notes.get(key, '')[:38]}")
            print("  " + "-" * 66)
            print(f"  {'REWARD':<20} {reward.get('reward', 0):>6.1f}")

            failing = [k for k in ORDER if k in reward and reward[k] != 1.0]
            if failing:
                print(f"\n  failing: {', '.join(failing)}")
                for key in failing:
                    if notes.get(key):
                        print(f"    {key}: {notes[key]}")

            site = trial / "artifacts" / "app" / "site"
            if site.is_dir():
                print(f"\n  click it yourself:  ./serve.sh {site}")
        return 0

    print("jobs exist but none produced a reward — check the trial logs")
    return 1


if __name__ == "__main__":
    sys.exit(main())
