#!/usr/bin/env bash
# Harbor mounts this task's tests/ at /tests and runs this script after the
# agent finishes. Absolute paths throughout, per the Harbor task docs.
set -uo pipefail

SITE_DIR="${SITE_DIR:-/site}"
mkdir -p /logs/verifier

# test_site.py writes /logs/verifier/reward.json itself, so the exit code here
# is informational — the reward file is what Harbor reads.
python3 /tests/test_site.py "$SITE_DIR" 2>&1 | tee /logs/verifier/report.txt
exit 0
