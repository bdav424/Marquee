"""Cache remote poster art to disk.

The display never hotlinks. Art is fetched once, stored next to the page, and
served from the same box — so the phone makes one request to one host and the
wall stays up if Alamo's CDN is having a day.

Not TMDB-specific: Alamo publishes its own poster images, so most art comes
straight from the feed.
"""

from __future__ import annotations

import hashlib
import urllib.request
from pathlib import Path

USER_AGENT = "winchester-marquee/1.0 (+self-hosted, single theater)"

# Extensions we will write. Anything else is stored as .jpg, since Alamo's
# imgix URLs often carry query strings rather than a clean suffix.
KNOWN_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".avif"}


def _suffix(url: str) -> str:
    stem = url.split("?", 1)[0]
    suffix = Path(stem).suffix.lower()
    return suffix if suffix in KNOWN_SUFFIXES else ".jpg"


def cache_image(url: str | None, slug: str, cache_dir: Path | str) -> str | None:
    """Download once, return a display-relative path, or None on failure.

    Already-cached art is never re-fetched, so a 6-hour cron costs one request
    per new title rather than one per title per cycle. A missing poster is a
    fallback tile in the UI, not a failed cycle, so every error returns None
    rather than raising.
    """
    if not url:
        return None

    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    # The URL is part of the filename hash: when Alamo swaps the art for a
    # title, the slug is unchanged but the URL is not, so the new art is
    # fetched instead of the stale file being served forever.
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:8]
    dest = cache_dir / f"{slug}-{digest}{_suffix(url)}"
    relative = f"posters/{dest.name}"

    if dest.exists() and dest.stat().st_size > 0:
        return relative

    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = response.read()
    except OSError:
        return None
    if not data:
        return None

    tmp = dest.with_suffix(dest.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(dest)
    return relative


def prune(cache_dir: Path | str, keep: set[str]) -> int:
    """Delete cached art no longer referenced. Returns the count removed.

    Without this the poster directory grows forever on a box that is meant to
    run untouched for months.
    """
    cache_dir = Path(cache_dir)
    if not cache_dir.is_dir():
        return 0
    removed = 0
    for path in cache_dir.iterdir():
        if path.name == ".gitkeep" or not path.is_file():
            continue
        if f"posters/{path.name}" not in keep:
            path.unlink()
            removed += 1
    return removed
