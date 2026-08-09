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
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dataclasses import replace  # noqa: E402

from marquee import tmdb  # noqa: E402
from marquee import reasons as reason_book  # noqa: E402
from marquee.adapters import alamo, filmratings  # noqa: E402
from marquee.build import build_snapshot, write_snapshot  # noqa: E402
from marquee.images import cache_image, prune  # noqa: E402
from marquee.model import Snapshot, Title  # noqa: E402
from marquee.series import load_series_config  # noqa: E402
from marquee.severity import load_config  # noqa: E402

DISPLAY_JSON = ROOT / "web" / "data" / "marquee.json"
RAW_CACHE = ROOT / "cache" / "last-good.json"
REASON_CACHE = ROOT / "cache" / "reasons.json"
NEEDS_REASON = ROOT / "logs" / "needs-reason.txt"
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


def enrich(titles: list[Title]) -> list[Title]:
    """Cache poster art and fill runtime/genres/synopsis from TMDB.

    Enrichment is best-effort by design. Alamo already supplies the title,
    showtimes, certification and poster, so a TMDB outage costs detail, not
    the display. The one thing worth caring about is `genres`: the Horror
    backstop is the only content signal that still works while rating reasons
    are unavailable, and it needs them.
    """
    have_key = bool(os.environ.get("TMDB_API_KEY", "").strip())
    if not have_key:
        log("TMDB_API_KEY not set — skipping enrichment "
            "(no runtime, genres or synopsis; the Horror backstop is off)")

    enriched, failures = [], 0
    for title in titles:
        poster = cache_image(title.poster_source, title.slug, POSTER_DIR)
        extra = {}
        if have_key:
            try:
                hit = tmdb.search_movie(title.name)
                if hit:
                    found = tmdb.enrich(hit["id"])
                    extra = {
                        "runtime_minutes": found["runtime_minutes"],
                        "genres": found["genres"],
                        "synopsis": found["synopsis"],
                    }
                    # Alamo's certification wins; TMDB's is the fallback.
                    if not title.mpa_rating and found["certification"]:
                        extra["mpa_rating"] = found["certification"]
            except Exception as exc:
                failures += 1
                log(f"  tmdb: {title.name}: {str(exc)[:80]}")
        enriched.append(replace(title, poster=poster, **extra))

    kept = {t.poster for t in enriched if t.poster}
    dropped = prune(POSTER_DIR, kept)
    log(f"enriched {len(enriched)} titles "
        f"({failures} tmdb failures, {len(kept)} posters, {dropped} pruned)")
    return enriched


# filmratings.com is behind Imperva bot protection: no query parameter is
# honoured, a POST returns the unfiltered page byte-for-byte, and its scripts
# expose no search endpoint. Reaching it would mean defeating an access
# control. Left in place and switchable in case that ever changes, but off.
CARA_ENABLED = os.environ.get("MARQUEE_TRY_CARA", "").strip() == "1"


def resolve_reasons(titles: list[Title]) -> list[Title]:
    """Attach MPA rating reasons, and report anything still missing one.

    Order: the hand-kept book in config/reasons.toml first, then the on-disk
    cache from any previous lookup, then CARA if it has been switched on.

    A title with no reason keeps mpa_reason None and scores `unknown`. That is
    the honest state — it shows a question mark rather than being quietly
    treated as clean — and it lands in logs/needs-reason.txt as a
    ready-to-paste stub.
    """
    book = reason_book.load()
    cache = filmratings.ReasonCache(REASON_CACHE)
    resolved = []
    from_book = from_cache = looked_up = errors = 0
    missing: list[str] = []

    for title in titles:
        if title.mpa_reason:
            resolved.append(title)
            continue

        text = reason_book.lookup(title.name, book)
        if text:
            from_book += 1
            resolved.append(replace(title, mpa_reason=text))
            continue

        found = cache.get(title.name)
        if found is not None and found.usable:
            from_cache += 1
            resolved.append(replace(title, mpa_reason=found.reason))
            continue

        if CARA_ENABLED and found is None:
            try:
                found = filmratings.lookup(
                    title.name, expect_certification=title.mpa_rating
                )
                cache.put(title.name, found)
                looked_up += 1
                if found.usable:
                    resolved.append(replace(title, mpa_reason=found.reason))
                    continue
            except filmratings.LookupFailed as exc:
                errors += 1
                log(f"  cara: {title.name}: {str(exc)[:70]}")

        missing.append(title.name)
        resolved.append(title)

    cache.save()
    write_needs_reason(missing)

    log(f"reasons: {from_book} from the book, {from_cache} cached, "
        f"{looked_up} looked up, {errors} errors, {len(missing)} still unknown")
    if missing:
        log(f"  add them to config/reasons.toml — stub in {NEEDS_REASON.name}")
    return resolved


def write_needs_reason(missing: list[str]) -> None:
    """Leave a paste-ready block for the titles that still need a reason."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    if not missing:
        NEEDS_REASON.write_text("# Every title has a rating reason.\n")
        return
    NEEDS_REASON.write_text(reason_book.stub_for(sorted(set(missing))))


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
        payload = alamo.fetch_json(alamo.SCHEDULE_URL)
        titles = alamo.to_titles(payload)
        log(f"fetched {len(titles)} titles from {alamo.SCHEDULE_URL}")
    except alamo.DiscoveryPending as exc:
        log(f"SHAPE: {exc}")
        return emit_stale()
    except Exception:
        log("fetch failed:\n" + traceback.format_exc())
        return emit_stale()

    titles = enrich(titles)
    titles = resolve_reasons(titles)

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
