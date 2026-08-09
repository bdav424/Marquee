"""The normalised data model the display reads.

This is deliberately *our* shape, not Alamo's. Endpoint discovery has not run,
so the feed's field names are unknown — but the display does not need to know
them. A future `marquee/adapters/alamo.py` maps the real feed onto these
types, and it is the only module that will need to change once the shape is
known.

Everything downstream of here — severity, series, the display JSON, the widget
— is written against this contract and is unaffected by what Alamo actually
returns.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class Showing:
    """One screening of one title."""

    showtime: datetime
    format: str | None = None          # "35mm", "70mm", "DCP"
    auditorium: str | None = None
    sold_out: bool = False
    # Raw series/event strings exactly as the feed carried them. Resolution to
    # a visual treatment happens later, so the raw value survives for the
    # reconciliation report.
    series_tags: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Title:
    """A film, plus every showing of it in the window."""

    slug: str
    name: str
    showings: list[Showing] = field(default_factory=list)

    # From the feed, or from filmratings.com / IMDb fallback.
    mpa_rating: str | None = None      # "R", "PG-13", "NR"
    mpa_reason: str | None = None      # the reason string the parser reads

    # From TMDB enrichment.
    runtime_minutes: int | None = None
    release_year: int | None = None
    genres: list[str] = field(default_factory=list)
    synopsis: str | None = None
    poster: str | None = None          # local cached path, never a remote URL
    # Where the art came from, before caching. Alamo publishes its own poster
    # images, so this is usually filled from the feed and TMDB is only needed
    # for runtime, genres and synopsis.
    poster_source: str | None = None

    @property
    def series_tags(self) -> list[str]:
        """Every distinct series tag across this title's showings."""
        seen: list[str] = []
        for showing in self.showings:
            for tag in showing.series_tags:
                if tag not in seen:
                    seen.append(tag)
        return seen


@dataclass(frozen=True)
class Snapshot:
    """One fetch cycle's worth of schedule, as cached to disk."""

    theater: str
    fetched_at: datetime
    titles: list[Title] = field(default_factory=list)
    # True when this snapshot came from cache because the fetch failed. The
    # display shows stale data with a visible timestamp rather than a blank
    # screen, so this drives that banner.
    stale: bool = False
