#!/usr/bin/env bash
# Harbor mounts this task's tests/ at /tests and runs this after the agent.
# check.py writes /logs/verifier/reward.json itself.
set -uo pipefail

SITE_DIR="${SITE_DIR:-/app/site}"
mkdir -p /logs/verifier

python3 /tests/check.py "$SITE_DIR" 2>&1 | tee /logs/verifier/report.txt
exit 0
