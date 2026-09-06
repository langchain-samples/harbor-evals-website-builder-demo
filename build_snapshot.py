"""Build the Harbor task's sandbox snapshot once, so runs don't pay for it.

Harbor builds a snapshot from `environment/Dockerfile` on first use, but it
never sets `fs_capacity_bytes` — so the snapshot gets LangSmith's default
filesystem size (16 GiB) for a ~1.6GB image, and it does not expose the
builder's cpu/memory either. That combination is what turned a two-minute
image build into a twenty-six-minute wait with no output.

This calls the SDK directly with the knobs Harbor hides:

  * a right-sized filesystem
  * a bigger builder sandbox
  * a build-log callback, so the wait is observable
  * a real timeout

Run it once. Then pin the result on every harbor run:

    --env langsmith \\
    --ek snapshot_name=site-builder-playwright \\
    --ek create_snapshot=false

    python build_snapshot.py                 # build (skips if it exists)
    python build_snapshot.py --list          # what snapshots exist
    python build_snapshot.py --rebuild       # delete and rebuild
    python build_snapshot.py --delete        # remove it
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

PROJECT = Path(__file__).resolve().parent
load_dotenv(PROJECT / ".env")

CONTEXT = PROJECT / "dataset" / "add-booking-form" / "environment"
SNAPSHOT_NAME = os.environ.get("DEMO_SNAPSHOT", "site-builder-playwright")

# Left unset on purpose. The Dockerfile path runs BuildKit inside a *builder*
# sandbox that itself boots from LangSmith's 16 GiB default snapshot, and the
# captured snapshot cannot be smaller than that:
#
#   fs_capacity_bytes (3221225472) cannot be smaller than snapshot (17179869184)
#
# So 16 GiB is the floor here and there is nothing to tune. A smaller
# filesystem is only reachable via create_snapshot(docker_image=...), which
# needs the image in a registry LangSmith can pull.
FS_CAPACITY = None
BUILDER_VCPUS = 4
BUILDER_MEM = 8 * 1024**3
BUILD_TIMEOUT = 3600

# Applies to every HTTP call the client makes, capture included.
HTTP_TIMEOUT = 1800.0

# The server's failure message asks for a retry, so honour it.
ATTEMPTS = 3


def client():
    from langsmith.sandbox import SandboxClient

    if not os.environ.get("LANGSMITH_API_KEY"):
        sys.exit("LANGSMITH_API_KEY is not set (is it in .env?)")
    # SandboxClient defaults to timeout=10.0 — a ten-second HTTP read
    # timeout applied to every call, including capture_snapshot, which blocks
    # until a multi-gigabyte filesystem has been captured. That is what the
    # earlier `httpx2.ReadTimeout` was, and almost certainly what Harbor's
    # own 26-minute hang was waiting on too.
    return SandboxClient(timeout=HTTP_TIMEOUT)


def find(sdk, name: str):
    for snap in sdk.list_snapshots(name_contains=name):
        if getattr(snap, "name", None) == name:
            return snap
    return None


def is_ready(snap) -> bool:
    """A snapshot record can exist while its capture failed.

    That is what bit us: the record was created, `status` was `failed`, and
    treating name-existence as success made this script report a usable
    snapshot while Harbor immediately died on `Snapshot creation failed`.
    """
    return str(getattr(snap, "status", "")).lower() in {"ready", "available", "succeeded", "active"}


def show(sdk) -> int:
    snaps = sdk.list_snapshots()
    if not snaps:
        print("no snapshots in this workspace")
        return 0
    print(f"{'name':<30} {'status':<10} {'size':<10} id")
    print("-" * 92)
    for snap in snaps:
        size = getattr(snap, "fs_capacity_bytes", None)
        size = f"{size / 1024**3:.1f} GiB" if size else "?"
        status = str(getattr(snap, "status", "?"))
        flag = "" if is_ready(snap) else "   <-- not usable"
        print(f"{getattr(snap, 'name', '?'):<30} {status:<10} {size:<10} {getattr(snap, 'id', '?')}{flag}")
    return 0


def build(sdk, rebuild: bool) -> int:
    existing = find(sdk, SNAPSHOT_NAME)
    if existing and is_ready(existing) and not rebuild:
        print(f"snapshot {SNAPSHOT_NAME!r} is ready (id {existing.id})")
        print("\nPin it on your harbor run with:")
        print(f"  --env langsmith --ek snapshot_name={SNAPSHOT_NAME} --ek create_snapshot=false")
        return 0
    if existing:
        why = "rebuild requested" if rebuild else f"status is {getattr(existing, 'status', '?')}"
        print(f"deleting snapshot {existing.id} ({why}) …")
        sdk.delete_snapshot(existing.id)

    dockerfile = CONTEXT / "Dockerfile"
    if not dockerfile.is_file():
        sys.exit(f"no Dockerfile at {dockerfile}")

    print(f"building {SNAPSHOT_NAME!r}")
    print(f"  context:     {CONTEXT.relative_to(PROJECT)}")
    print(f"  fs capacity: {'default (16 GiB floor)' if FS_CAPACITY is None else str(FS_CAPACITY // 1024**3) + ' GiB'}")
    print(f"  builder:     {BUILDER_VCPUS} vcpu / {BUILDER_MEM / 1024**3:.0f} GiB")
    print(f"  build/http:  {BUILD_TIMEOUT}s / {HTTP_TIMEOUT:.0f}s\n" + "-" * 70)

    started = time.time()
    last = [started]

    def on_log(line: str) -> None:
        # Timestamp each line so the slow phase is obvious rather than a
        # spinner that tells you nothing.
        now = time.time()
        gap = now - last[0]
        last[0] = now
        marker = "  <-- slow" if gap > 20 else ""
        print(f"[{now - started:6.1f}s +{gap:5.1f}s] {line.rstrip()[:120]}{marker}", flush=True)

    # The server's own message on failure is "Please retry", and it failed in
    # 12 seconds the first time — so a retry is the documented remedy rather
    # than a guess.
    snapshot = None
    for attempt in range(1, ATTEMPTS + 1):
        if attempt > 1:
            print(f"\n--- attempt {attempt} of {ATTEMPTS} ---", flush=True)
            stale = find(sdk, SNAPSHOT_NAME)
            if stale:
                sdk.delete_snapshot(stale.id)
        try:
            snapshot = sdk.create_snapshot_from_dockerfile(
                SNAPSHOT_NAME,
                dockerfile="Dockerfile",
                context=str(CONTEXT),
                **({"fs_capacity_bytes": FS_CAPACITY} if FS_CAPACITY else {}),
                vcpus=BUILDER_VCPUS,
                mem_bytes=BUILDER_MEM,
                on_build_log=on_log,
                timeout=BUILD_TIMEOUT,
            )
        except Exception as exc:
            print(f"\nattempt {attempt} raised: {type(exc).__name__}: {exc}")
            snapshot = None

        # Whether the call returned or raised, check what actually landed —
        # a returned object is not proof the capture succeeded.
        landed = find(sdk, SNAPSHOT_NAME)
        if landed and is_ready(landed):
            snapshot = landed
            break
        if landed:
            print(f"snapshot status is {getattr(landed, 'status', '?')}: "
                  f"{getattr(landed, 'status_message', '')}")
        snapshot = None

    elapsed = time.time() - started
    print("-" * 70)
    if not snapshot:
        print(f"failed after {elapsed / 60:.1f} min and {ATTEMPTS} attempt(s).")
        print("Falling back to --env docker is the pragmatic move; the reward")
        print("table and the LangSmith experiment are identical either way.")
        return 1

    print(f"ready in {elapsed / 60:.1f} min — id {snapshot.id} (status {snapshot.status})")
    print("\nPin it on your harbor run with:")
    print(f"  --env langsmith --ek snapshot_name={SNAPSHOT_NAME} --ek create_snapshot=false")
    return 0


def remove(sdk) -> int:
    snap = find(sdk, SNAPSHOT_NAME)
    if not snap:
        print(f"no snapshot named {SNAPSHOT_NAME!r}")
        return 0
    sdk.delete_snapshot(snap.id)
    print(f"deleted {SNAPSHOT_NAME!r} ({snap.id})")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--list", action="store_true", help="list snapshots and exit")
    group.add_argument("--rebuild", action="store_true", help="delete and rebuild")
    group.add_argument("--delete", action="store_true", help="delete and exit")
    args = parser.parse_args()

    sdk = client()
    if args.list:
        return show(sdk)
    if args.delete:
        return remove(sdk)
    return build(sdk, rebuild=args.rebuild)


if __name__ == "__main__":
    sys.exit(main())
