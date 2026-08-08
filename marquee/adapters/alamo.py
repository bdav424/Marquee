"""Alamo Drafthouse schedule adapter — Winchester, VA.

STATUS: endpoint FOUND. Field mapping still not written.

drafthouse.com is an Angular SPA — the served HTML is a ~4.5 KB shell with no
schedule in it at all, so the hydration-payload approach this module started
with was a dead end. The real source is a JSON API:

    GET /s/mother/v2/schedule/market/winchester   ->  ~630 KB, {"data": ...}

Confirmed live on 2026-08-08. Sibling endpoints found by scanning Alamo's own
JS bundles are listed in KNOWN_ENDPOINTS; `/schedule/collection/` is the likely
home of series programming (Terror Tuesday and friends).

An undocumented API can change without notice, so this module is written to
fail loudly rather than silently: a shape it does not recognise raises instead
of returning a half-empty schedule.

`to_titles()` still raises — the field inventory has not been read yet. Run:

    python3 -m marquee.adapters.alamo discover
"""

from __future__ import annotations

import gzip
import json
import re
import urllib.error
import urllib.request
import zlib
from typing import Any

from marquee.model import Title

MARKET_SLUG = "winchester"

# The brief's note is confirmed by observation: Alamo's edge serves 503 to
# clients that do not look like browsers. These headers are the minimum that
# gets a real response.
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Connection": "keep-alive",
}

API_ROOT = "https://drafthouse.com/s/mother"

# The schedule endpoint. Confirmed returning JSON for this market.
SCHEDULE_URL = f"{API_ROOT}/v2/schedule/market/{MARKET_SLUG}"

# Tried in order.
CANDIDATE_URLS = [SCHEDULE_URL]

# Harvested from Alamo's JS bundles. Not all are useful and none are
# documented; kept as a map of the surface for when the schedule endpoint
# alone is not enough.
KNOWN_ENDPOINTS = [
    "/v2/schedule/market/{market}",       # the one we use
    "/v2/schedule/venue/",
    "/v2/schedule/session/",
    "/v2/schedule/presentation",
    "/v2/schedule/collection/",           # series programming lives here
    "/v2/schedule/collection/only-at-the-alamo/",
    "/v2/schedule/coming-soon/",
    "/v2/schedule/featured/",
    "/v2/core/venue/theater/",
    "/v2/core/page/",
    "/v1/market/",
    "/v1/nearest-cinema/",
]

# The HTML shell carries no schedule, so these are kept only to recognise the
# situation if someone points this module at a page again.
LEGACY_PAGE_URLS = [
    f"https://drafthouse.com/{MARKET_SLUG}",
    f"https://drafthouse.com/{MARKET_SLUG}/showtimes",
]

# Hydration payload shapes, most specific first.
PAYLOAD_PATTERNS = [
    re.compile(
        r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL
    ),
    re.compile(r"self\.__next_f\.push\(\s*(\[.*?\])\s*\)", re.DOTALL),
    re.compile(r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\});", re.DOTALL),
    re.compile(r"window\.__APOLLO_STATE__\s*=\s*(\{.*?\});", re.DOTALL),
]


class DiscoveryPending(NotImplementedError):
    """Raised where a real response is required and has never been obtained."""


def fetch_raw(url: str, timeout: int = 30) -> str:
    """GET a page with browser-realistic headers. Returns decoded HTML."""
    req = urllib.request.Request(url, headers=BROWSER_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read()
        encoding = resp.headers.get("Content-Encoding", "")
    if encoding == "gzip":
        body = gzip.decompress(body)
    elif encoding == "deflate":
        body = zlib.decompress(body, -zlib.MAX_WBITS)
    return body.decode("utf-8", errors="replace")


def fetch_json(url: str, timeout: int = 30) -> Any:
    """GET a JSON endpoint. Raises DiscoveryPending on a non-JSON answer."""
    body = fetch_raw(url, timeout=timeout)
    stripped = body.lstrip()
    if not stripped[:1] in "{[":
        raise DiscoveryPending(
            f"{url} returned {len(body)} bytes that are not JSON. If this looks "
            "like HTML, the endpoint moved — rescan the JS bundles for /s/ paths."
        )
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise DiscoveryPending(f"{url} returned malformed JSON: {exc}") from exc


def unwrap(payload: Any) -> Any:
    """Strip Alamo's {"data": ...} envelope when present."""
    if isinstance(payload, dict) and set(payload) == {"data"}:
        return payload["data"]
    return payload


def extract_payload(html: str) -> Any:
    """Legacy: pull a hydration blob out of page source.

    Retained only to produce a clear message. drafthouse.com serves a bare
    Angular shell, so this will never find a schedule — use fetch_json.
    """
    for pattern in PAYLOAD_PATTERNS:
        match = pattern.search(html)
        if not match:
            continue
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
    raise DiscoveryPending(
        "No hydration payload in the HTML — expected, since drafthouse.com is "
        f"an Angular SPA whose shell carries no schedule. Use {SCHEDULE_URL}"
    )


def _walk(node: Any, path: str = "$", depth: int = 0, out: dict | None = None) -> dict:
    """Flatten a nested payload into path -> sample value, for the inventory."""
    out = {} if out is None else out
    if depth > 12:
        return out
    if isinstance(node, dict):
        for key, value in node.items():
            _walk(value, f"{path}.{key}", depth + 1, out)
    elif isinstance(node, list):
        if node:
            _walk(node[0], f"{path}[]", depth + 1, out)
    else:
        out.setdefault(path, node)
    return out


# Fields the display needs. discover() reports which of these it can find, so
# the gap between "what we want" and "what Alamo actually sends" is explicit.
WANTED = [
    "title", "showtime", "format", "auditorium", "sold out",
    "mpa rating", "rating reason", "series / event tag",
]


def find_strings(node: Any, pattern: re.Pattern, path: str = "$",
                 depth: int = 0, out: list | None = None, limit: int = 12) -> list:
    """Locate string values matching a pattern, with their paths.

    Used to hunt for MPA rating-reason text, which is the input the whole
    content-signal layer depends on and which may not be published at all.
    """
    out = [] if out is None else out
    if depth > 14 or len(out) >= limit:
        return out
    if isinstance(node, dict):
        for key, value in node.items():
            find_strings(value, pattern, f"{path}.{key}", depth + 1, out, limit)
    elif isinstance(node, list):
        for i, value in enumerate(node[:40]):
            find_strings(value, pattern, f"{path}[{i}]", depth + 1, out, limit)
    elif isinstance(node, str) and pattern.search(node):
        out.append((path, node))
    return out


# Fields the display needs. discover() reports which it can find, so the gap
# between "what we want" and "what Alamo actually sends" is explicit.
WANTED = {
    "title": ["title", "name", "filmname", "presentationtitle"],
    "showtime": ["showtime", "sessiondatetime", "starttime", "time", "date"],
    "format": ["format", "presentationformat", "projection"],
    "auditorium": ["auditorium", "screen", "theatre", "room"],
    "sold out": ["soldout", "status", "seatsavailable", "available"],
    "mpa rating": ["rating", "mpaa", "certification"],
    "rating reason": ["ratingreason", "reason", "ratingdescription", "advisory"],
    "series / event": ["collection", "series", "event", "programtag", "tag"],
    "runtime": ["runtime", "duration", "length"],
    "synopsis": ["synopsis", "overview", "description", "plot"],
    "poster": ["poster", "image", "artwork", "keyart"],
}

# What a rating reason looks like in the wild.
REASON_PATTERN = re.compile(
    r"\b(rated\s+(?:g|pg|pg-13|r|nc-17)\b|for\s+(?:strong|brief|some|graphic|"
    r"pervasive|mild|sequences of)\b)", re.I
)


def discover(url: str | None = None) -> dict:
    """Fetch the schedule API and report its field inventory. Run this first."""
    errors = []
    for candidate in ([url] if url else CANDIDATE_URLS):
        try:
            payload = unwrap(fetch_json(candidate))
        except (urllib.error.URLError, OSError) as exc:
            errors.append(f"{candidate}: {exc}")
            continue

        inventory = _walk(payload)

        print(f"# source     : {candidate}")
        print(f"# leaf paths : {len(inventory)}")
        print(f"# top level  : {type(payload).__name__} "
              f"{list(payload)[:12] if isinstance(payload, dict) else f'len={len(payload)}'}")

        print("\n## field inventory\n")
        for path, sample in sorted(inventory.items()):
            print(f"{path[:76]:<76}  {str(sample)[:56]}")

        print("\n## fields the display needs\n")
        flat = " ".join(inventory).lower().replace("_", "").replace("-", "")
        for want, tokens in WANTED.items():
            hits = [t for t in tokens if t in flat]
            mark = "FOUND  " if hits else "MISSING"
            print(f"  {mark}  {want:<16} {('via ' + ', '.join(hits[:3])) if hits else ''}")

        # The question that decides whether the severity parser has any input.
        print("\n## MPA rating-reason strings\n")
        found = find_strings(payload, REASON_PATTERN)
        if found:
            for path, text in found[:8]:
                print(f"  {path[:60]}\n     {text[:130]}\n")
        else:
            print("  NONE FOUND. Alamo does not appear to publish rating reasons.")
            print("  Every title will score `unknown` unless a second source is")
            print("  added (filmratings.com, or IMDb's parents guide).")

        return {"url": candidate, "payload": payload, "inventory": inventory,
                "reasons": found}

    raise DiscoveryPending(
        "Every candidate URL failed:\n  " + "\n  ".join(errors)
    )


def to_titles(payload: Any) -> list[Title]:
    """Map Alamo's payload onto the normalised model.

    NOT IMPLEMENTED, on purpose. Every field name here would be a guess until
    discover() has run against a live response. Write this from the inventory
    that discover() prints, and it is the only function that needs writing —
    severity, series resolution, the build pipeline, the companion page and
    the widget are all already written against marquee.model and will work
    unchanged the moment this returns real Titles.
    """
    raise DiscoveryPending(
        "Field mapping not written: no live Alamo response has ever been "
        "observed from this environment. Run `python3 -m marquee.adapters."
        "alamo discover` from a host with outbound access, then write this "
        "function against the printed inventory."
    )


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "discover":
        discover(sys.argv[2] if len(sys.argv) > 2 else None)
    else:
        print(__doc__)
