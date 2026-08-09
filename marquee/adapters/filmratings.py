"""filmratings.com (CARA) adapter — the MPA rating-reason source.

WHY THIS EXISTS: Alamo publishes a certification and no reason text, and TMDB
does not model reason strings at all. filmratings.com is the MPA's own CARA
database and publishes the exact sentences the severity parser was written
for — "Rated R for strong bloody violence, language throughout...". Without
this adapter every title scores `unknown` and nothing ever greys.

STATUS: search endpoint confirmed live; extraction confirmed to read a real
reason out of a real page. Result verification is written but has NOT been
confirmed against live markup — see extract_reason_for.

A CARA search returns every film whose name contains the query. The first
version of this took the first "Rated X for" on the page and attributed it to
whatever was searched for, which pulled an R-rated stranger's reason onto a
PG-13 film. That is the worst thing this adapter can do: not a gap, but a
confident wrong verdict with an explanation attached. Reasons are now accepted
only when the film's own title appears just above them and, when the caller
knows it, the certification agrees.

Run `discover()` from a host with outbound access to confirm or correct it:

    python3 -m marquee.adapters.filmratings discover "The Long Dark"

BE POLITE. This is a small public lookup service, not an API. Reasons never
change once assigned, so results are cached permanently on disk and only new
titles are ever queried — a full cycle costs a handful of requests, and
repeat cycles cost none. Keep it that way.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Confirmed live 2026-08-08. /Search/GetSearchResults 404s and was dropped;
# the x/y parameters make no difference to the response, so one request per
# lookup is all this costs.
SEARCH_CANDIDATES = [
    "https://www.filmratings.com/Search?filmTitle={q}",
]

# Seconds between requests. Deliberately unhurried.
REQUEST_DELAY = 1.5

CERTIFICATIONS = "G|PG-13|PG|NC-17|R"

# The whole point. Matches the CARA sentence wherever it appears — inside a
# JSON string, an HTML text node, or a table cell — without depending on the
# structure around it. Stops at a tag, quote, or sentence end.
# Newlines are allowed inside the reason: CARA's markup wraps the sentence
# across lines, and excluding \n made the whole pattern miss on real pages.
# The <>" exclusions still bound it to a single text node or JSON string.
REASON_RE = re.compile(
    rf"\bRated\s+({CERTIFICATIONS})\s+for\s+([^<>\"]{{5,400}}?)\s*(?:[.]|</|\"|$)",
    re.IGNORECASE,
)

# Some pages give the reason without the "Rated X for" lead-in.
BARE_REASON_RE = re.compile(
    r"\b(?:rating\s+(?:reason|descriptor)s?|reason)\s*[:\-]\s*"
    r"([^<>\"]{5,400}?)\s*(?:[.]|</|\"|$)",
    re.IGNORECASE,
)

_PUNCT = re.compile(r"[^a-z0-9]+")


class LookupFailed(RuntimeError):
    """Network or shape failure. Never raised for 'film simply not found'."""


@dataclass(frozen=True)
class Reason:
    certification: str | None
    reason: str | None
    source: str

    @property
    def usable(self) -> bool:
        return bool(self.reason)


def normalise_title(title: str) -> str:
    """Loose key for comparing an Alamo title to a CARA title."""
    text = title.lower()
    text = re.sub(r"\b(the|a|an)\b", " ", text)
    # Alamo decorates titles: "Movie Party: Jaws", "Jaws (1975)", "Jaws - 35mm"
    text = re.sub(r"\(.*?\)", " ", text)
    return _PUNCT.sub(" ", text).strip()


# Only these are stripped. An earlier version matched any short word before a
# colon, which ate "Spider-Man:" out of "Spider-Man: Brand New Day" and sent a
# search for the wrong film entirely. A colon is part of plenty of real titles,
# so the list is a whitelist and stays one.
PROGRAMMING_PREFIXES = (
    "terror tuesday", "weird wednesday", "video vortex", "movie party",
    "champagne cinema", "kids camp", "time capsule", "alamo time capsule",
    "only at the alamo", "the alamo presents", "alamo presents",
    "afs presents", "cinema club", "big screen classics",
    # Seen on the live Winchester schedule.
    "psycho cinema presents", "genreblast film festival",
)

# Anything of the form "<strand> Presents:" is programming, not a title.
# Real titles almost never contain the word, and this catches strands the
# whitelist has not met yet.
_PRESENTS_RE = re.compile(r"^.{2,40}?\s+presents\s*[:\-]\s*", re.IGNORECASE)

# Alamo appends these to repertory bookings. CARA files the film, not the
# booking: "Terminator 2: Judgment Day 35th Anniversary" is catalogued as
# "Terminator 2: Judgment Day".
_REISSUE_RE = re.compile(
    r"\s*[:\-]?\s*\b\d{1,3}(?:st|nd|rd|th)\s+anniversary\b.*$", re.IGNORECASE
)

_PREFIX_RE = re.compile(
    r"^(?:" + "|".join(re.escape(p) for p in PROGRAMMING_PREFIXES) + r")\s*[:\-]\s*",
    re.IGNORECASE,
)


def strip_decoration(title: str) -> str:
    """Drop Alamo's programming decoration before searching CARA.

    "Terror Tuesday: The Thing" matches nothing in the MPA database; "The
    Thing" does. But "Spider-Man: Brand New Day" must be left alone — the
    colon is part of the title.
    """
    cleaned = _PREFIX_RE.sub("", title).strip()
    cleaned = _PRESENTS_RE.sub("", cleaned).strip()
    cleaned = _REISSUE_RE.sub("", cleaned).strip()
    cleaned = re.sub(r"\s+[-–]\s+(35mm|70mm|dcp|imax).*$", "", cleaned, flags=re.I)
    # A trailing year helps a human disambiguate and only confuses the search.
    cleaned = re.sub(r"\s*\((?:19|20)\d{2}\)\s*$", "", cleaned).strip()
    return cleaned or title


def fetch(url: str, timeout: int = 25) -> str:
    request = urllib.request.Request(url, headers=BROWSER_HEADERS)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, OSError) as exc:
        raise LookupFailed(f"{url}: {exc}") from exc


# How far back from a reason to look for the film title it belongs to. A CARA
# search result puts the title above its reason; this spans one result block
# without reaching into the previous one.
TITLE_WINDOW = 700


def _format(certification: str, body: str) -> str:
    return f"Rated {certification.upper()} for {' '.join(body.split())}."


def extract_reason(text: str) -> tuple[str | None, str | None]:
    """First reason on the page, with NO check of which film it belongs to.

    Only safe on a page known to describe a single film. For a search results
    page use extract_reason_for(), which verifies the title — otherwise the
    first result on the page gets attributed to whatever you searched for.
    """
    match = REASON_RE.search(text)
    if match:
        return match.group(1).upper(), _format(match.group(1), match.group(2))

    match = BARE_REASON_RE.search(text)
    if match:
        return None, " ".join(match.group(1).split())

    return None, None


def extract_reason_for(
    text: str, title: str, expect_certification: str | None = None
) -> tuple[str | None, str | None]:
    """The reason belonging to `title`, or (None, None).

    A CARA search for "The Thing" returns every film whose name contains those
    words. Taking the first reason on the page attributes a stranger's rating
    to our film — worse than having no reason at all, because a wrong verdict
    greys a title with a confident explanation attached.

    Two guards. The film's own title must appear in the markup just above the
    reason, and when the caller knows the certification from Alamo, it must
    agree. Failing either yields nothing, which leaves the title `unknown`.
    """
    wanted = normalise_title(strip_decoration(title))
    if not wanted:
        return None, None

    for match in REASON_RE.finditer(text):
        certification = match.group(1).upper()

        if expect_certification and certification != expect_certification.upper():
            continue

        window = text[max(0, match.start() - TITLE_WINDOW):match.start()]
        if wanted not in normalise_title(window):
            continue

        return certification, _format(certification, match.group(2))

    return None, None


def lookup(
    title: str,
    delay: float = REQUEST_DELAY,
    expect_certification: str | None = None,
) -> Reason:
    """Search CARA for a title's rating reason.

    Raises LookupFailed only on transport trouble. A film that genuinely is
    not in the database returns a Reason with reason=None, which the caller
    should cache so it is not asked again every cycle.
    """
    query = urllib.parse.quote(strip_decoration(title))
    errors = []

    for index, template in enumerate(SEARCH_CANDIDATES):
        url = template.format(q=query)
        if index:
            time.sleep(delay)
        try:
            body = fetch(url)
        except LookupFailed as exc:
            errors.append(str(exc))
            continue

        certification, reason = extract_reason_for(
            body, title, expect_certification
        )
        if reason:
            return Reason(certification, reason, url)

    if errors and len(errors) == len(SEARCH_CANDIDATES):
        raise LookupFailed("; ".join(errors[:2]))

    return Reason(None, None, "filmratings.com")


# --- persistent cache -------------------------------------------------------
# Reasons never change once CARA assigns them, so a hit is cached forever. A
# miss is cached for a week: a film may not be in the database on release day
# but appear later, and we should not re-ask on every single cycle meanwhile.

MISS_TTL = timedelta(days=7)


class ReasonCache:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.entries: dict = {}
        if self.path.exists():
            try:
                self.entries = json.loads(self.path.read_text())
            except (json.JSONDecodeError, OSError):
                self.entries = {}

    def get(self, title: str) -> Reason | None:
        entry = self.entries.get(normalise_title(title))
        if not entry:
            return None
        if not entry.get("reason"):
            stamp = entry.get("checked_at")
            try:
                checked = datetime.fromisoformat(stamp) if stamp else None
            except ValueError:
                checked = None
            if not checked or datetime.now(timezone.utc) - checked > MISS_TTL:
                return None
        return Reason(entry.get("certification"), entry.get("reason"),
                      entry.get("source", "cache"))

    def put(self, title: str, reason: Reason) -> None:
        self.entries[normalise_title(title)] = {
            "title": title,
            "certification": reason.certification,
            "reason": reason.reason,
            "source": reason.source,
            "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.entries, indent=2, ensure_ascii=False))
        tmp.replace(self.path)


def _post(url: str, fields: dict, timeout: int = 25) -> str:
    data = urllib.parse.urlencode(fields).encode()
    request = urllib.request.Request(
        url, data=data,
        headers=dict(BROWSER_HEADERS,
                     **{"Content-Type": "application/x-www-form-urlencoded"}),
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, OSError) as exc:
        raise LookupFailed(f"POST {url}: {exc}") from exc


# Field names lifted off the live page by inspect(). filmTitle was never one
# of them — it was invented, which is why every query returned the same page.
CANDIDATE_PARAMS = [
    "searchForAMovie", "filmTitle", "title", "movieTitle",
    "query", "q", "search", "txtTitle",
]


def probe(title: str) -> None:
    """Find how the search actually takes a query.

    Compares each candidate parameter against a baseline request with no
    query at all. A parameter the server honours changes the response; one it
    ignores returns the same bytes. Then scans the page's own JavaScript for
    the endpoint it calls, which is how the Alamo feed was found.
    """
    wanted = strip_decoration(title)
    encoded = urllib.parse.quote(wanted)
    base = "https://www.filmratings.com/Search"

    baseline = fetch(base)
    print(f"# query    : {wanted!r}")
    print(f"# baseline : {len(baseline)} bytes with no query at all\n")

    print("## GET parameters\n")
    # Compared against each other, not only against the baseline. Every
    # parameter returning the same page as every other is the tell that none
    # of them is honoured — measuring each against the no-query baseline made
    # them all look like they did something.
    sizes: dict[str, int] = {}
    for name in CANDIDATE_PARAMS:
        try:
            body = fetch(f"{base}?{name}={encoded}")
        except LookupFailed as exc:
            print(f"  {name:18} ERR {str(exc)[:60]}")
            continue
        sizes[name] = len(body)
        echoed = wanted.lower() in body.lower()
        print(f"  {name:18} {len(body):>7} bytes   echoed {echoed}")
        time.sleep(REQUEST_DELAY)

    if sizes:
        spread = max(sizes.values()) - min(sizes.values())
        print(f"\n  spread across parameters: {spread} bytes")
        print("  Nothing echoed and a small spread means the query is being "
              "dropped\n  and the same page comes back whatever you ask for.")

    print("\n## POST searchForAMovie\n")
    try:
        body = _post(base, {"searchForAMovie": wanted})
        delta = len(body) - len(baseline)
        print(f"  {len(body):>7}  delta {delta:>+7}  "
              f"echoed {wanted.lower() in body.lower()}")
        cert, reason = extract_reason_for(body, wanted)
        print(f"  verified extraction: {cert} / {reason!r}")
    except LookupFailed as exc:
        print(f"  ERR {str(exc)[:80]}")

    print("\n## endpoints in the page's own JavaScript\n")
    scripts = [
        src if src.startswith("http") else "https://www.filmratings.com" + src
        for src in re.findall(r"<script[^>]+src=[\"']([^\"']+)[\"']", baseline)
    ]
    found = set()
    for src in scripts[:8]:
        try:
            js = fetch(src)
        except LookupFailed:
            continue
        print(f"  scanned {src.split('/')[-1][:48]} ({len(js)} bytes)")
        found.update(
            re.findall(r"[\"'](/[A-Za-z0-9/_.\-]{3,70})[\"']", js)
        )
        time.sleep(REQUEST_DELAY)

    interesting = sorted(
        path for path in found
        if any(k in path.lower() for k in ("search", "api", "rating", "film", "title"))
    )
    print(f"\n  {len(interesting)} candidate paths:")
    for path in interesting[:40]:
        print("    " + path)


def inspect(title: str) -> None:
    """Report how the search page actually accepts a query.

    Two different queries came back within a byte of each other, which means
    filmTitle in the query string is being ignored and the page returned is a
    generic one. This prints what the page does with a query so the real
    mechanism can be used instead of guessed at.
    """
    wanted = strip_decoration(title)
    url = SEARCH_CANDIDATES[0].format(q=urllib.parse.quote(wanted))
    body = fetch(url)

    print(f"# query   : {wanted!r}")
    print(f"# url     : {url}")
    print(f"# bytes   : {len(body)}")
    print(f"# echoed  : {wanted.lower() in body.lower()}   "
          "(is our query anywhere in the response?)\n")

    forms = re.findall(r"<form[^>]*>", body, re.I)
    print(f"## forms ({len(forms)})\n")
    for form in forms[:6]:
        print("  " + " ".join(form.split())[:220])

    fields = re.findall(
        r"<(?:input|select|textarea)[^>]*?name=[\"']([^\"']+)[\"'][^>]*>", body, re.I
    )
    print(f"\n## field names ({len(fields)})\n")
    for name in dict.fromkeys(fields):
        print("  " + name)

    paths = set(re.findall(r"[\"'](/[A-Za-z0-9/_.\-]{3,60})[\"']", body))
    interesting = sorted(
        p for p in paths
        if any(k in p.lower() for k in ("search", "api", "rating", "title", "film"))
    )
    print(f"\n## paths that look like search or data ({len(interesting)})\n")
    for path in interesting[:30]:
        print("  " + path)

    token = re.search(r"__RequestVerificationToken", body)
    print(f"\n## ASP.NET antiforgery token present: {bool(token)}")
    if token:
        print("   A POST with that token is likely how search submits.")


def discover(title: str) -> None:
    """Probe every candidate and report what came back. Run this first."""
    query = urllib.parse.quote(strip_decoration(title))
    print(f"# searching for: {strip_decoration(title)!r} (from {title!r})\n")

    for template in SEARCH_CANDIDATES:
        url = template.format(q=query)
        try:
            body = fetch(url)
        except LookupFailed as exc:
            print(f"ERR   {url}\n      {str(exc)[:110]}\n")
            continue

        kind = "JSON" if body.lstrip()[:1] in "{[" else "HTML"
        naive_cert, naive = extract_reason(body)
        certification, reason = extract_reason_for(body, title)
        print(f"{kind}  {len(body):>7} bytes  {url}")
        print(f"      VERIFIED (used) : {certification} / {reason!r}")
        print(f"      first-on-page   : {naive_cert} / {naive!r}")
        if naive and naive != reason:
            print("      ^ these differ — verification is doing real work here")

        if not reason:
            hits = re.findall(rf"[^<>]*\bRated\s+(?:{CERTIFICATIONS})\b[^<>]*", body)
            if hits:
                print("      no VERIFIED match. Reasons on the page were:")
                for hit in hits[:6]:
                    print(f"        {' '.join(hit.split())[:130]}")
                print("      If one of these IS the film, the title-window check")
                print("      needs widening or the markup differs from expected.")
            else:
                print("      no rating-shaped text at all in this response")
                print(f"      first 400 chars: {' '.join(body.split())[:400]}")
        print()
        time.sleep(REQUEST_DELAY)


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 2 and sys.argv[1] == "discover":
        discover(" ".join(sys.argv[2:]))
    elif len(sys.argv) > 2 and sys.argv[1] == "inspect":
        inspect(" ".join(sys.argv[2:]))
    elif len(sys.argv) > 2 and sys.argv[1] == "probe":
        probe(" ".join(sys.argv[2:]))
    else:
        print(__doc__)
