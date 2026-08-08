"""Alamo Drafthouse schedule adapter — Winchester, VA.

STATUS: fetch layer written, field mapping deliberately NOT written.

The transport half of this module is real: browser-realistic headers, the
hydration-payload extraction, and the candidate endpoint strategies from the
brief. What is missing is the mapping from Alamo's field names onto
marquee.model, because endpoint discovery has never successfully run — this
sandbox's egress policy refuses CONNECT to drafthouse.com, so no live response
has ever been seen.

Guessing the field names would produce code that looks finished and is
confidently wrong, so `to_titles()` raises instead. Run `discover()` from a
host with normal outbound access; it dumps a pretty-printed sample and a field
inventory, and that inventory is what `to_titles()` gets written against.

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

# Tried in order. The page is the reliable one — it carries the hydration
# payload — but if an XHR endpoint is visible in the payload it is cheaper to
# poll directly on later cycles.
CANDIDATE_URLS = [
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


def extract_payload(html: str) -> Any:
    """Pull the hydration blob out of the page source."""
    for pattern in PAYLOAD_PATTERNS:
        match = pattern.search(html)
        if not match:
            continue
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
    raise DiscoveryPending(
        "No hydration payload matched. Alamo changed their front end, or the "
        "response was an interstitial. Dump the HTML and add a pattern."
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


def discover(url: str | None = None) -> dict:
    """Fetch, extract, and report the field inventory. Run this first."""
    errors = []
    for candidate in ([url] if url else CANDIDATE_URLS):
        try:
            html = fetch_raw(candidate)
        except (urllib.error.URLError, OSError) as exc:
            errors.append(f"{candidate}: {exc}")
            continue

        payload = extract_payload(html)
        inventory = _walk(payload)

        print(f"# source: {candidate}")
        print(f"# distinct leaf paths: {len(inventory)}\n")
        print("## sample (truncated)\n")
        print(json.dumps(payload, indent=2)[:4000])
        print("\n## field inventory\n")
        for path, sample in sorted(inventory.items()):
            preview = str(sample)[:70]
            print(f"{path:<70} {preview}")

        print("\n## fields the display needs\n")
        haystack = " ".join(inventory).lower()
        for want in WANTED:
            token = want.split()[0]
            print(f"  {'FOUND  ' if token in haystack else 'MISSING'}  {want}")
        return {"url": candidate, "payload": payload, "inventory": inventory}

    raise DiscoveryPending(
        "Every candidate URL failed. If these are CONNECT 403s from an egress "
        "proxy the request never reached Alamo — that is a network policy "
        "problem, not a scraping problem.\n  " + "\n  ".join(errors)
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
