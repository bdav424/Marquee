"""TMDB enrichment: poster art, runtime, genres, synopsis, US certification.

UNVERIFIED AGAINST THE LIVE API. The endpoint shapes here follow TMDB's
documented v3 contract, but this sandbox's egress policy blocks
api.themoviedb.org, so not one call in this module has ever been executed.
Treat the response-shape handling as reviewed-but-untested code.

Two things the brief is right about and this module depends on:

  * Certification lives on /movie/{id}/release_dates under the US entry, and
    can be had in one call via append_to_response=release_dates.
  * TMDB's `note` field is effectively always empty. It does NOT carry the
    MPA rating reason string — TMDB's maintainers declined to model rating
    justifications. So this module returns a certification ("R") and never
    pretends to supply a reason. The reason string comes from Alamo's own
    feed, filmratings.com, or IMDb's parents guide.

Poster art is downloaded once and cached to disk. The display never hotlinks.
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

API_ROOT = "https://api.themoviedb.org/3"
IMAGE_ROOT = "https://image.tmdb.org/t/p"
POSTER_SIZE = "w500"

USER_AGENT = "winchester-marquee/1.0 (+self-hosted, single theater)"


class TMDBError(RuntimeError):
    pass


def _key() -> str:
    key = os.environ.get("TMDB_API_KEY", "").strip()
    if not key:
        raise TMDBError("TMDB_API_KEY is not set. See docs/deploy.md.")
    return key


def _get(path: str, **params) -> dict:
    params["api_key"] = _key()
    url = f"{API_ROOT}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                               "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def search_movie(title: str, year: int | None = None) -> dict | None:
    """Best match for a title, or None. Alamo's titles are usually exact."""
    params = {"query": title, "include_adult": "false"}
    if year:
        params["year"] = year
    results = _get("/search/movie", **params).get("results", [])
    return results[0] if results else None


def us_certification(release_dates: dict) -> str | None:
    """Pull the US certification out of an append_to_response payload.

    A film often has several US entries (theatrical, digital, festival); the
    first non-empty certification wins, since they rarely disagree and an
    empty string is TMDB's way of saying "not recorded".
    """
    for entry in release_dates.get("results", []):
        if entry.get("iso_3166_1") != "US":
            continue
        for release in entry.get("release_dates", []):
            cert = (release.get("certification") or "").strip()
            if cert:
                return cert
    return None


def enrich(tmdb_id: int) -> dict:
    """Everything the display needs about one film, in a single call."""
    data = _get(f"/movie/{tmdb_id}", append_to_response="release_dates")
    return {
        "tmdb_id": tmdb_id,
        "runtime_minutes": data.get("runtime") or None,
        "genres": [g["name"] for g in data.get("genres", [])],
        "synopsis": (data.get("overview") or "").strip() or None,
        "certification": us_certification(data.get("release_dates", {})),
        "poster_path": data.get("poster_path"),
        # Deliberately absent: any claim to a rating *reason*. TMDB does not
        # carry one, and inventing a fallback here would quietly defeat the
        # severity parser's honest-unknown handling.
    }


def cache_poster(poster_path: str, slug: str, cache_dir: Path) -> str | None:
    """Download poster art once. Returns a display-relative path.

    Already-cached art is never re-fetched, so a 6-hour cron costs one request
    per new title rather than one per title per cycle.
    """
    if not poster_path:
        return None
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(poster_path).suffix or ".jpg"
    dest = cache_dir / f"{slug}{suffix}"
    rel = f"posters/{dest.name}"

    if dest.exists() and dest.stat().st_size > 0:
        return rel

    url = f"{IMAGE_ROOT}/{POSTER_SIZE}{poster_path}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()
    except OSError:
        # A missing poster is a fallback tile, not a failed cycle.
        return None
    if not data:
        return None
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(dest)
    return rel
