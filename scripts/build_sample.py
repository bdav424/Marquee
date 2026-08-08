#!/usr/bin/env python3
"""Generate a display JSON from INVENTED sample data.

>>> THIS IS NOT REAL ALAMO DATA. <<<

Endpoint discovery has not run — the egress policy blocks drafthouse.com — so
nothing here was captured from the feed. Showtimes, auditoriums and series
assignments are made up. Rating strings are real MPA phrasings, chosen to
exercise every branch of the severity parser.

Its purpose is to let the display be built and verified against the normalised
contract in marquee/model.py before the real feed exists. Once discovery runs,
a real adapter replaces this and the display does not change.

    python3 scripts/build_sample.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from marquee.build import build_snapshot, write_snapshot  # noqa: E402
from marquee.model import Showing, Snapshot, Title  # noqa: E402
from marquee.series import load_series_config  # noqa: E402
from marquee.severity import load_config  # noqa: E402

BASE = datetime.now().astimezone().replace(hour=12, minute=0, second=0, microsecond=0)


def at(day: int, hour: int, minute: int = 0) -> datetime:
    return BASE + timedelta(days=day, hours=hour - 12, minutes=minute)


SAMPLE_TITLES = [
    # Trips violence >= 3 and sexual >= 1. Greyed.
    Title(
        slug="the-long-dark",
        name="The Long Dark",
        mpa_rating="R",
        mpa_reason=(
            "Rated R for strong bloody violence, language throughout, "
            "and some sexual content."
        ),
        runtime_minutes=138,
        genres=["Thriller", "Drama"],
        synopsis="A hitchhiker takes the last ride out of a town that is already gone.",
        poster="posters/the-long-dark.jpg",
        showings=[
            Showing(at(0, 19, 30), format="DCP", auditorium="Theater 3"),
            Showing(at(1, 16, 0), format="DCP", auditorium="Theater 3", sold_out=True),
        ],
    ),
    # Horror genre backstop with NO reason string. All severities unknown,
    # flagged on genre alone. Exercises honest-unknown display.
    Title(
        slug="salt-flats",
        name="Salt Flats",
        mpa_rating="NR",
        mpa_reason=None,
        runtime_minutes=94,
        genres=["Horror"],
        synopsis="Something is walking the dry lake bed, and it is keeping pace.",
        poster="posters/salt-flats.jpg",
        showings=[
            Showing(
                at(1, 21, 45),
                format="35mm",
                auditorium="Theater 1",
                series_tags=["Terror Tuesday"],
            )
        ],
    ),
    # Severe language only. Must NOT grey out — proves the language rule.
    Title(
        slug="commission-sales",
        name="Commission Sales",
        mpa_rating="R",
        mpa_reason="Rated R for pervasive language and some drug use.",
        runtime_minutes=112,
        genres=["Comedy"],
        synopsis="Four brokers, one quota, and a fax machine that will not stop.",
        poster="posters/commission-sales.jpg",
        showings=[
            Showing(at(0, 20, 15), format="DCP", auditorium="Theater 2"),
            Showing(at(2, 18, 30), format="DCP", auditorium="Theater 2"),
        ],
    ),
    # Clean. Renders at full saturation.
    Title(
        slug="paper-boats",
        name="Paper Boats",
        mpa_rating="PG",
        mpa_reason="Rated PG for mild thematic elements.",
        runtime_minutes=101,
        genres=["Family", "Adventure"],
        synopsis="Two siblings map a river that is not on any map.",
        poster="posters/paper-boats.jpg",
        showings=[
            Showing(
                at(2, 11, 0),
                format="DCP",
                auditorium="Theater 4",
                series_tags=["Kids Camp"],
            )
        ],
    ),
    # Moderate violence only — under the threshold. Must NOT grey out.
    Title(
        slug="ironwood",
        name="Ironwood",
        mpa_rating="PG-13",
        mpa_reason="Rated PG-13 for sequences of violence and action.",
        runtime_minutes=127,
        genres=["Action"],
        synopsis="A logging dispute becomes a siege.",
        poster="posters/ironwood.jpg",
        showings=[Showing(at(1, 17, 0), format="DCP", auditorium="Theater 1")],
    ),
    # Unparseable reason string. Severity unknown, surfaced honestly, and the
    # fragments land in diagnostics for vocabulary extension.
    Title(
        slug="the-gleaners-hour",
        name="The Gleaner's Hour",
        mpa_rating="R",
        mpa_reason="Rated R for aberrant conduct and unsettling tableaux.",
        runtime_minutes=118,
        genres=["Drama"],
        synopsis="A restorer of church frescoes begins repainting the saints.",
        poster="posters/the-gleaners-hour.jpg",
        showings=[
            Showing(
                at(3, 22, 0),
                format="35mm",
                auditorium="Theater 1",
                series_tags=["Weird Wednesday"],
            )
        ],
    ),
    # Unrecognised series strand — still badges, lands in diagnostics.
    Title(
        slug="hydroplane",
        name="Hydroplane",
        mpa_rating="R",
        mpa_reason="Rated R for graphic nudity and language.",
        runtime_minutes=99,
        genres=["Drama"],
        synopsis="A speed record attempt on a lake that freezes early.",
        poster="posters/hydroplane.jpg",
        showings=[
            Showing(
                at(2, 21, 0),
                format="DCP",
                auditorium="Theater 2",
                series_tags=["Cursed Film Club", "21+"],
            )
        ],
    ),
]


def main() -> int:
    snapshot = Snapshot(
        theater="Alamo Drafthouse Winchester",
        fetched_at=datetime.now().astimezone(),
        titles=SAMPLE_TITLES,
        stale=False,
    )
    payload = build_snapshot(snapshot, load_config(), load_series_config())
    out = write_snapshot(payload, ROOT / "web" / "data" / "marquee.json")

    d = payload["diagnostics"]
    print(f"wrote {out.relative_to(ROOT)}")
    print(f"  titles          : {d['title_count']}")
    print(f"  greyed          : {d['flagged_count']}")
    print(f"  unknown ratings : {d['unknown_reason_count']}")
    print(f"  vocab gaps      : {d['unmatched_reason_fragments']}")
    print(f"  series gaps     : {d['unrecognised_series']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
