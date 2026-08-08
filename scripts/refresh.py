#!/usr/bin/env python3
"""Cron entry point: fetch, enrich, build, write.

Every six hours. Alamo posts roughly a week out, so polling harder buys
nothing and is just rudeness with extra steps.

Degradation is the whole design here. A failed cycle must never blank the
wall: the previous snapshot is retained, re-emitted with `stale: true`, and
the display shows its age in the header. Only a successful fetch replaces it.

    python3 scripts/refresh.py            # one cycle
    python3 scripts/refresh.py --dry-run  # fetch and report, write nothing
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from marquee.adapters import alamo  # noqa: E402
from marquee.build import build_snapshot, write_snapshot  # noqa: E402
from marquee.model import Snapshot  # noqa: E402
from marquee.series import load_series_config  # noqa: E402
from marquee.severity import load_config  # noqa: E402

DISPLAY_JSON = ROOT / "web" / "data" / "marquee.json"
RAW_CACHE = ROOT / "cache" / "last-good.json"
POSTER_DIR = ROOT / "web" / "posters"
LOG_DIR = ROOT / "logs"
PARSE_LOG = LOG_DIR / "parse-failures.jsonl"
RUN_LOG = LOG_DIR / "refresh.log"


def log(message: str) -> None:
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    line = f"{stamp}  {message}"
    print(line)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with open(RUN_LOG, "a") as fh:
        fh.write(line + "\n")


def record_parse_failures(payload: dict) -> None:
    """Append this cycle's vocabulary gaps so the keyword sets can grow.

    Step 5's requirement. Reading this file is how config/marquee.toml and
    config/series.toml get extended over time — it is the only record of what
    the parser could not understand.
    """
    diagnostics = payload.get("diagnostics", {})
    gaps = {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "unmatched_reason_fragments": diagnostics.get("unmatched_reason_fragments", []),
        "unparsed_reason_strings": diagnostics.get("unparsed_reason_strings", []),
        "unrecognised_series": diagnostics.get("unrecognised_series", []),
    }
    if not any(gaps[k] for k in list(gaps)[1:]):
        return
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with open(PARSE_LOG, "a") as fh:
        fh.write(json.dumps(gaps, ensure_ascii=False) + "\n")

    log(
        f"vocabulary gaps: {len(gaps['unmatched_reason_fragments'])} fragments, "
        f"{len(gaps['unparsed_reason_strings'])} unreadable strings, "
        f"{len(gaps['unrecognised_series'])} unknown series -> {PARSE_LOG.name}"
    )


def emit_stale() -> int:
    """Re-publish the last good snapshot, marked stale. Never blank the screen."""
    if not DISPLAY_JSON.exists():
        log("FAILED and no previous snapshot exists — display will show an error.")
        return 1
    payload = json.loads(DISPLAY_JSON.read_text())
    payload["stale"] = True
    payload["generated_at"] = datetime.now().astimezone().isoformat()
    write_snapshot(payload, DISPLAY_JSON)
    log(f"serving stale cache from {payload.get('fetched_at')}")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="fetch and report, write nothing")
    args = parser.parse_args()

    log("cycle start")
    try:
        result = alamo.discover()
        titles = alamo.to_titles(result["payload"])
    except alamo.DiscoveryPending as exc:
        log(f"BLOCKED: {exc}")
        return emit_stale()
    except Exception:
        log("fetch failed:\n" + traceback.format_exc())
        return emit_stale()

    # TMDB enrichment goes here once discovery lands: for each title, search,
    # enrich, cache the poster. Deliberately not wired up in advance — it
    # keys off fields to_titles() does not yet produce.

    snapshot = Snapshot(
        theater="Alamo Drafthouse Winchester",
        fetched_at=datetime.now().astimezone(),
        titles=titles,
        stale=False,
    )
    payload = build_snapshot(snapshot, load_config(), load_series_config())
    record_parse_failures(payload)

    if args.dry_run:
        d = payload["diagnostics"]
        log(f"dry run: {d['title_count']} titles, {d['flagged_count']} dimmed "
            f"(nothing written)")
        return 0

    write_snapshot(payload, DISPLAY_JSON)
    RAW_CACHE.parent.mkdir(parents=True, exist_ok=True)
    write_snapshot(payload, RAW_CACHE)
    log(f"wrote {payload['diagnostics']['title_count']} titles, "
        f"{payload['diagnostics']['flagged_count']} dimmed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
