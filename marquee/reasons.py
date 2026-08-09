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


def stub_for(titles) -> str:
    """A paste-ready TOML block for titles that still have no reason."""
    lines = [
        "# Paste into config/reasons.toml under [reasons].",
        "# Look each title up at https://www.filmratings.com in a browser and",
        "# copy the sentence verbatim — the parser reads the wording, so do",
        "# not paraphrase it.",
        "",
    ]
    for name in titles:
        lines.append(f'"{name}" = ""')
    return "\n".join(lines) + "\n"
