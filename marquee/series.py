"""Resolve a showing's series/event tag to a visual treatment.

One-night programming is the point of the display, so an unrecognised series
tag still gets a badge rather than being dropped — falling through to the
default treatment and being reported for reconciliation.

Matching is substring-based against a normalised form of whatever string the
feed carries. That is deliberate: the feed's exact field shape is not yet
known, so this resolves off text rather than off a schema.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "series.toml"

_NORMALISE = re.compile(r"[^a-z0-9+]+")


@dataclass(frozen=True)
class Treatment:
    key: str
    label: str
    background: str
    foreground: str
    one_night: bool
    priority: int
    # Normalised substrings that resolve to this treatment, longest first.
    match: tuple[str, ...] = ()
    # The verbatim feed string this resolved from; None for the default.
    source: str | None = None
    recognised: bool = True


@dataclass(frozen=True)
class SeriesConfig:
    treatments: list[Treatment]
    default: Treatment
    # Normalised tags that are categories rather than series, and are dropped.
    ignore: tuple[str, ...] = ()


def _normalise(text: str) -> str:
    """Lowercase, collapse punctuation to single spaces, keep '+' for '21+'."""
    return _NORMALISE.sub(" ", text.lower()).strip()


def _contains_phrase(haystack: str, phrase: str) -> bool:
    """Whole-word phrase containment over normalised text.

    Padding both sides forces word boundaries, so the pattern "rep" cannot
    match inside "prepare" the way a raw substring test would. Both inputs are
    already normalised to space-delimited tokens, which is what makes this
    sufficient without a regex.
    """
    return f" {phrase} " in f" {haystack} "


def load_series_config(path: Path | str = DEFAULT_CONFIG_PATH) -> SeriesConfig:
    with open(path, "rb") as fh:
        raw = tomllib.load(fh)

    defaults = raw.get("defaults", {})
    default = Treatment(
        key="unrecognised",
        label=defaults.get("label", "SERIES"),
        background=defaults.get("background", "#4A4A52"),
        foreground=defaults.get("foreground", "#F5F5F0"),
        one_night=bool(defaults.get("one_night", False)),
        priority=int(defaults.get("priority", 0)),
        recognised=False,
    )

    treatments = []
    for entry in raw.get("series", []):
        treatments.append(
            Treatment(
                key=entry["key"],
                label=entry["label"],
                background=entry["background"],
                foreground=entry["foreground"],
                one_night=bool(entry.get("one_night", False)),
                priority=int(entry.get("priority", 0)),
                # Longest first so "movie party" wins over bare "party".
                match=tuple(
                    sorted(
                        (_normalise(m) for m in entry.get("match", [])),
                        key=len,
                        reverse=True,
                    )
                ),
            )
        )

    # Resolution order is by priority, so a high-priority strand claims an
    # ambiguous string before a lower-priority one can.
    treatments.sort(key=lambda t: t.priority, reverse=True)

    ignore = tuple(
        _normalise(t) for t in raw.get("ignore", {}).get("tags", [])
    )

    return SeriesConfig(treatments=treatments, default=default, ignore=ignore)


def resolve(tags: list[str] | str | None, config: SeriesConfig) -> list[Treatment]:
    """Resolve feed tag string(s) to treatments, highest priority first.

    An unrecognised non-empty tag resolves to the default treatment carrying
    its source string, so it still badges and still shows up in the
    reconciliation report. Returns [] only when there is genuinely no tag.
    """
    if tags is None:
        return []
    if isinstance(tags, str):
        tags = [tags]

    resolved: list[Treatment] = []
    seen: set[str] = set()

    for tag in tags:
        if not tag or not tag.strip():
            continue
        normalised = _normalise(tag)
        if not normalised:
            continue
        # Categories masquerading as series ("New Releases") are dropped here
        # rather than badged — see [ignore] in config/series.toml.
        if any(_contains_phrase(normalised, i) for i in config.ignore):
            continue

        match = None
        for treatment in config.treatments:
            if any(_contains_phrase(normalised, pattern) for pattern in treatment.match):
                match = treatment
                break

        if match is None:
            resolved.append(
                Treatment(
                    key=config.default.key,
                    label=tag.strip().upper(),
                    background=config.default.background,
                    foreground=config.default.foreground,
                    one_night=config.default.one_night,
                    priority=config.default.priority,
                    source=tag,
                    recognised=False,
                )
            )
            continue

        if match.key in seen:
            continue
        seen.add(match.key)
        resolved.append(
            Treatment(
                key=match.key,
                label=match.label,
                background=match.background,
                foreground=match.foreground,
                one_night=match.one_night,
                priority=match.priority,
                source=tag,
                recognised=True,
            )
        )

    resolved.sort(key=lambda t: t.priority, reverse=True)
    return resolved


def primary(tags: list[str] | str | None, config: SeriesConfig) -> Treatment | None:
    """The single badge that gets the strong treatment. None if untagged."""
    resolved = resolve(tags, config)
    return resolved[0] if resolved else None


def unrecognised(tags: list[str] | str | None, config: SeriesConfig) -> list[str]:
    """Feed strings that matched no configured series — the reconcile backlog."""
    return [t.source for t in resolve(tags, config) if not t.recognised and t.source]
