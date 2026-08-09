"""Which Alamo markets to build, and which one loads first.

The display was built for one theatre and still opens on one theatre. This
module is what lets it open on a *different* one without becoming a listings
site: a short, explicit list of markets you actually care about, each built
into its own snapshot on the same cron.

The market slug is the only thing that varies between Alamo locations. Same
endpoint, same payload shape, same field names — so nothing downstream of the
adapter knows or cares which city it is reading.

Fails soft, like the rest of the config layer: a missing or malformed file
falls back to Winchester alone rather than taking the cycle down.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "config" / "markets.toml"

FALLBACK_SLUG = "winchester"
FALLBACK_NAME = "Winchester, VA"


@dataclass(frozen=True)
class Market:
    slug: str
    name: str


@dataclass(frozen=True)
class MarketConfig:
    markets: list[Market]
    default: str

    @property
    def default_market(self) -> Market:
        for market in self.markets:
            if market.slug == self.default:
                return market
        return self.markets[0]

    def get(self, slug: str) -> Market | None:
        for market in self.markets:
            if market.slug == slug:
                return market
        return None


def _fallback() -> MarketConfig:
    return MarketConfig([Market(FALLBACK_SLUG, FALLBACK_NAME)], FALLBACK_SLUG)


def load(path: Path | str = DEFAULT_PATH) -> MarketConfig:
    """Read the market list. Any problem returns the single default market."""
    try:
        with open(path, "rb") as fh:
            raw = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError):
        return _fallback()

    markets: list[Market] = []
    seen: set[str] = set()
    for entry in raw.get("market") or []:
        if not isinstance(entry, dict):
            continue
        slug = str(entry.get("slug") or "").strip().lower()
        # A duplicate slug would build the same board twice and give the
        # picker two identical rows.
        if not slug or slug in seen:
            continue
        seen.add(slug)
        markets.append(Market(slug, str(entry.get("name") or slug).strip()))

    if not markets:
        return _fallback()

    default = str(raw.get("default") or "").strip().lower()
    # A default naming a market that is not built would open on a 404.
    if default not in seen:
        default = markets[0].slug
    return MarketConfig(markets, default)


def snapshot_name(slug: str) -> str:
    """The filename a market's snapshot is written to.

    The default market also writes marquee.json, so anything already pointed
    at that path — the widgets, an old bookmark — keeps working untouched.
    """
    return f"{slug}.json"
