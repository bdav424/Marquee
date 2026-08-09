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
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from marquee.model import Showing, Title

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


def _index(items: Any, key: str = "slug") -> dict:
    """Slug -> object, for the lookup tables the schedule references by slug."""
    out = {}
    for item in items or []:
        if isinstance(item, dict) and item.get(key):
            out[item[key]] = item
    return out


# Age policies that are just the MPA certification restated. Alamo also uses
# this field for real admission policies ("Rated PG with Adult Focus"), which
# ARE worth badging — so only the plain restatements are filtered out.
PLAIN_AGE_POLICY = re.compile(r"^rated-(g|pg|pg-13|r|nc-17)(-standard)?$", re.I)


def _zone(tzname: str):
    """ZoneInfo for a name, or None where no tz database is installed.

    Termux ships no IANA database and no tzdata package, so ZoneInfo raises
    there. That must not take the whole cycle down — the offset is
    recoverable from the feed without it.
    """
    try:
        return ZoneInfo(tzname)
    except Exception:
        return None


def _showtime(session: dict) -> datetime:
    """Cinema-local aware datetime for a session.

    The feed gives the same instant twice: showTimeClt naive-but-local and
    showTimeUtc naive-but-UTC. Their difference IS the cinema's offset for
    that session, so the offset is read off the data rather than looked up.

    That matters for more than tidiness. A tz database is not always present —
    Termux has none — and ZoneInfo("America/New_York") raising there used to
    abort the entire fetch. It also handles daylight saving for free, since
    each session carries whatever offset applied on its own date.
    """
    local_raw = session.get("showTimeClt")
    utc_raw = session.get("showTimeUtc")

    if local_raw and utc_raw:
        local = datetime.fromisoformat(local_raw).replace(tzinfo=None)
        utc = datetime.fromisoformat(utc_raw).replace(tzinfo=None)
        # Rounded to the minute: no real zone is offset by seconds, and the
        # feed has been seen to carry them.
        offset = timedelta(minutes=round((local - utc).total_seconds() / 60))
        return local.replace(tzinfo=timezone(offset))

    tzname = session.get("cinemaTimeZoneName") or "America/New_York"
    zone = _zone(tzname)

    if utc_raw:
        parsed = datetime.fromisoformat(utc_raw)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        # Without a tz database the instant is still right; only the label it
        # is rendered under changes, and the display localises anyway.
        return parsed.astimezone(zone) if zone else parsed

    if local_raw:
        parsed = datetime.fromisoformat(local_raw)
        if zone:
            return parsed.replace(tzinfo=zone)
        # Last resort: no offset available from anywhere. Read the wall time
        # as the box's own, which is right when the box sits at the cinema.
        return parsed.astimezone()

    raise DiscoveryPending(
        f"session {session.get('sessionId')} carries neither showTimeUtc nor "
        "showTimeClt — the schedule shape changed."
    )


def _humanise(value: str) -> str:
    """Turn a slug into a label. Values already in prose are left alone.

    primaryCollectionSlug arrives as "psycho-cinema" while
    presentationAttributes carry a proper name, so the two need levelling
    before either reaches the display.
    """
    if " " in value or "-" not in value:
        return value
    return " ".join(word.capitalize() for word in value.split("-"))


def _series_tags(presentation: dict, attributes: dict) -> list[str]:
    """Human-readable series/event tags for a presentation.

    Alamo spreads this across several fields. All of them are collected as raw
    strings; deciding which are real series and which are noise is
    config/series.toml's job, not this module's.
    """
    tags: list[str] = []

    for key in ("superTitle", "event", "eventType", "primaryCollectionSlug"):
        value = presentation.get(key)
        if isinstance(value, str) and value.strip():
            tags.append(_humanise(value.strip()))

    for slug in presentation.get("presentationAttributeSlugs") or []:
        attribute = attributes.get(slug)
        if not attribute:
            tags.append(_humanise(slug))
            continue
        # Respect Alamo's own judgement about what is worth showing a user.
        if attribute.get("isUserVisible") is False:
            continue
        tags.append(attribute.get("name") or slug)

    return tags


def _age_policy_tag(session: dict, policies: dict) -> list[str]:
    """The session's admission policy, when it says more than the rating does."""
    slug = session.get("agePolicySlug")
    if not slug or PLAIN_AGE_POLICY.match(slug):
        return []
    policy = policies.get(slug)
    return [policy.get("name") or slug] if policy else [slug]


def _poster(show: dict) -> str | None:
    """Best available poster URI. Alamo publishes its own art."""
    for image in show.get("posterImages") or []:
        if isinstance(image, dict) and image.get("uri"):
            return image["uri"]
    for key in ("portraitHeroImage", "landscapeHeroImage"):
        image = show.get(key)
        if isinstance(image, dict) and image.get("uri"):
            return image["uri"]
    return None


def to_titles(payload: Any) -> list[Title]:
    """Map Alamo's schedule payload onto the normalised model.

    Written against the live field inventory of
    /s/mother/v2/schedule/market/winchester, confirmed 2026-08-08.

    The join is sessions[].presentationSlug -> presentations[].slug. Sessions
    carry the time, screen, format and admission policy; presentations carry
    the film. Lookup tables (formats, agePolicies, presentationAttributes) are
    referenced by slug and resolved to human strings here.

    Note what is NOT set: mpa_reason. Alamo publishes the certification but no
    rating-reason text, so every title scores `unknown` until a second source
    supplies one. That is surfaced honestly rather than defaulted to clean.
    """
    data = unwrap(payload)
    if not isinstance(data, dict):
        raise DiscoveryPending(
            f"expected a JSON object at the top level, got {type(data).__name__}"
        )

    missing = [k for k in ("presentations", "sessions") if k not in data]
    if missing:
        raise DiscoveryPending(
            f"schedule payload is missing {missing}; got keys {list(data)[:12]}. "
            "The API shape changed — re-run discover."
        )

    formats = _index(data.get("formats"))
    age_policies = _index(data.get("agePolicies"))
    attributes = _index(data.get("presentationAttributes"))

    sessions_by_presentation: dict[str, list[dict]] = {}
    for session in data["sessions"]:
        if not isinstance(session, dict) or session.get("isHidden"):
            continue
        slug = session.get("presentationSlug")
        if slug:
            sessions_by_presentation.setdefault(slug, []).append(session)

    titles: list[Title] = []
    for presentation in data["presentations"]:
        if not isinstance(presentation, dict) or presentation.get("isHidden"):
            continue

        slug = presentation.get("slug")
        raw_sessions = sessions_by_presentation.get(slug, [])
        if not raw_sessions:
            # A presentation with no sessions is not playing in this window.
            continue

        show = presentation.get("show") or {}
        series = _series_tags(presentation, attributes)

        showings = []
        for session in raw_sessions:
            fmt = formats.get(session.get("formatSlug")) or {}
            screen = session.get("screenNumber")
            status = str(session.get("status") or "").upper().replace("_", "")
            showings.append(
                Showing(
                    showtime=_showtime(session),
                    format=fmt.get("title") or session.get("formatSlug"),
                    auditorium=f"Theater {screen}" if screen is not None else None,
                    sold_out=status == "SOLDOUT",
                    series_tags=series + _age_policy_tag(session, age_policies),
                )
            )

        titles.append(
            Title(
                slug=slug,
                name=show.get("title") or slug,
                showings=showings,
                mpa_rating=show.get("certification"),
                # Alamo does not publish rating reasons. See module docstring.
                mpa_reason=None,
                poster_source=_poster(show),
            )
        )

    if not titles:
        raise DiscoveryPending(
            f"parsed 0 titles from {len(data['presentations'])} presentations and "
            f"{len(data['sessions'])} sessions — the join key changed."
        )

    return titles


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "discover":
        discover(sys.argv[2] if len(sys.argv) > 2 else None)
    else:
        print(__doc__)
