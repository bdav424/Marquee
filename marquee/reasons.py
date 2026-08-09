"""MPA rating reasons kept by hand.

Every automatic source is closed. Alamo publishes a certification and no
reason text. TMDB does not model reasons. IMDb has the field only in its paid
bulk feed. filmratings.com, the MPA's own database and the origin of every one
of these sentences, sits behind Imperva bot protection — no query parameter is
honoured, a POST returns the unfiltered page byte-for-byte, and there is no
search endpoint in its JavaScript. Getting past that would mean defeating an
access control, which is not something this project will do.

So the reasons are typed in. That sounds worse than it is:

  * One theatre shows on the order of ten films at a time.
  * A reason never changes once CARA assigns it, so each title is entered
    once and never revisited.
  * refresh.py writes logs/needs-reason.txt with a ready-to-paste stub for
    every title still missing one, so the job is copy, paste, done.

Until a title has an entry it scores `unknown` and shows a question mark,
which is the honest state — not a guess, and not silently treated as clean.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from marquee.adapters.filmratings import strip_decoration

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "config" / "reasons.toml"

_PUNCT = re.compile(r"[^a-z0-9]+")


def normalise(title: str) -> str:
    """Loose key so a title matches however Alamo happens to decorate it.

    Programming prefixes are stripped with the same whitelist the CARA adapter
    uses, so "Terror Tuesday: The Thing" finds an entry filed under "The
    Thing" rather than needing its own.
    """
    text = strip_decoration(title).lower()
    text = re.sub(r"\b(the|a|an)\b", " ", text)
    text = re.sub(r"\(.*?\)", " ", text)
    return _PUNCT.sub(" ", text).strip()


def load(path: Path | str = DEFAULT_PATH) -> dict[str, str]:
    """Title key -> verbatim reason. Missing or unreadable file yields none."""
    path = Path(path)
    if not path.exists():
        return {}
    try:
        with open(path, "rb") as fh:
            raw = tomllib.load(fh)
    except (tomllib.TOMLDecodeError, OSError):
        # A typo in the file must not take the cycle down; the titles simply
        # stay unknown, which is the state they were already in.
        return {}

    out = {}
    for title, reason in (raw.get("reasons") or {}).items():
        if isinstance(reason, str) and reason.strip():
            out[normalise(title)] = reason.strip()
    return out


def load_exempt(path: Path | str = DEFAULT_PATH) -> set[str]:
    """Titles CARA never gave a descriptor, so none is coming.

    Rating descriptors only began in 1990. Taxi Driver, Phantom of the
    Paradise and Mothra vs. Godzilla carry a certification and nothing else,
    and no amount of looking will produce a sentence for them. Listing one
    here keeps it `unknown` — which is the truth, we do not know what is in it
    — while dropping it out of the needs-reason report so the report stays a
    list of work that can actually be done.
    """
    path = Path(path)
    if not path.exists():
        return set()
    try:
        with open(path, "rb") as fh:
            raw = tomllib.load(fh)
    except (tomllib.TOMLDecodeError, OSError):
        return set()
    return {
        normalise(title)
        for title in (raw.get("no_descriptor") or [])
        if isinstance(title, str) and title.strip()
    }


def is_exempt(title: str, exempt: set[str]) -> bool:
    return normalise(title) in exempt


def lookup(title: str, overrides: dict[str, str]) -> str | None:
    return overrides.get(normalise(title))


# CARA began issuing rating descriptors in 1990. Before that a film carried a
# certification and nothing else, so there is no sentence to go and find.
DESCRIPTOR_ERA_BEGINS = 1990


def predates_descriptors(release_year: int | None) -> bool:
    """True when no descriptor can exist for this film, whoever looks.

    Unknown year returns False: absent evidence, the honest assumption is that
    the sentence exists and simply has not been typed in. Better to ask for
    work that turns out to be impossible than to quietly write a title off.
    """
    return release_year is not None and release_year < DESCRIPTOR_ERA_BEGINS


def stub_for(titles) -> str:
    """A paste-ready TOML block for titles that still have no reason.

    Ordered newest first. A repertory booking and a first-run release both
    show a question mark, but only one of them is worth a trip to the browser
    on a Friday — the new release is what somebody is deciding about tonight.
    Sorting here means the lines worth doing are the lines at the top.

    Accepts either bare names or (name, release_year) pairs.
    """
    pairs = [t if isinstance(t, tuple) else (t, None) for t in titles]
    # Unknown year sorts with the new releases: an unrecognised title is far
    # more likely to be something TMDB has not indexed yet than a revival.
    pairs.sort(key=lambda p: (-(p[1] or 9999), p[0].lower()))

    lines = [
        "# Paste into config/reasons.toml under [reasons].",
        "# Look each title up at https://www.filmratings.com in a browser and",
        "# copy the sentence verbatim — the parser reads the wording, so do",
        "# not paraphrase it.",
        "#",
        "# Newest first. The top of this list is what is worth your time; a",
        "# question mark on a revival screening is an honest answer.",
        "",
    ]
    for name, year in pairs:
        stamp = f"  # {year}" if year else ""
        lines.append(f'"{name}" = ""{stamp}')
    return "\n".join(lines) + "\n"
