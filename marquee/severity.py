"""Parse MPA rating-reason strings into a per-category severity vector.

The MPA reason string follows a near-formal grammar: an intensity adverb
attached to a category noun, with clauses joined by commas and "and".

    "Rated R for strong bloody violence, language throughout,
     and some sexual content."

    -> violence: 3, language: 3, sexual: 1, substance: 0, frightening: 0

Severity is 1 (mild) / 2 (moderate) / 3 (severe), 0 for "parsed the string,
this category was not mentioned", and None for *unknown* — the string was
missing, or was present but yielded no recognisable category at all. Unknown
is never collapsed into 0; a title we could not read is not a title we know
to be clean.

All vocabulary and thresholds live in config/marquee.toml. Nothing here is
hardcoded.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "marquee.toml"

# Splits the reason into comma-segments, then each segment into conjunction
# fragments. Modifier inheritance is scoped to the segment.
_SEGMENT_SPLIT = re.compile(r"[,;]")
_FRAGMENT_SPLIT = re.compile(r"\band\b|&|/")


@dataclass(frozen=True)
class Config:
    categories: dict[str, list[str]]
    intensity: dict[int, list[str]]
    thresholds: dict[str, int | None]
    genre_flags: list[str]
    strip_prefixes: list[str]
    default_level: int
    inherit_modifiers: bool

    # (keyword, category), longest keyword first — longest-match wins so
    # "disturbing images" beats "disturbing".
    keywords: list[tuple[str, str]] = field(default_factory=list)

    @property
    def category_names(self) -> list[str]:
        return list(self.categories)


def load_config(path: Path | str = DEFAULT_CONFIG_PATH) -> Config:
    with open(path, "rb") as fh:
        raw = tomllib.load(fh)

    categories = {cat: list(words) for cat, words in raw.get("categories", {}).items()}
    for cat, words in raw.get("categories_extra", {}).items():
        categories.setdefault(cat, []).extend(words)

    intensity = {int(level): list(words) for level, words in raw.get("intensity", {}).items()}

    thresholds: dict[str, int | None] = {}
    for cat, value in raw.get("thresholds", {}).items():
        # `false` in TOML means "never flag on this category".
        thresholds[cat] = None if value is False else int(value)

    parser_cfg = raw.get("parser", {})
    keywords = sorted(
        ((word.lower(), cat) for cat, words in categories.items() for word in words),
        key=lambda pair: len(pair[0]),
        reverse=True,
    )

    return Config(
        categories=categories,
        intensity=intensity,
        thresholds=thresholds,
        genre_flags=list(raw.get("genre_flags", {}).get("tmdb_genres", [])),
        strip_prefixes=[p.lower() for p in parser_cfg.get("strip_prefixes", [])],
        default_level=int(parser_cfg.get("default_level", 2)),
        inherit_modifiers=bool(parser_cfg.get("inherit_modifiers_across_conjunction", True)),
        keywords=keywords,
    )


@dataclass(frozen=True)
class SeverityVector:
    """Per-category severity plus enough provenance to explain itself."""

    raw: str | None
    parsed: bool
    scores: dict[str, int | None]
    # category -> the fragments that produced its score, for the drill-in panel.
    evidence: dict[str, list[str]]
    # Fragments that matched no keyword. These are the extension backlog.
    unmatched: list[str]

    def score(self, category: str) -> int | None:
        return self.scores.get(category)

    def is_unknown(self, category: str) -> bool:
        return self.scores.get(category) is None


def _strip_prefix(text: str, config: Config) -> str:
    lowered = text.lower().strip()
    for prefix in config.strip_prefixes:
        if lowered.startswith(prefix):
            return text.strip()[len(prefix):].strip()
    return text.strip()


def _modifier_levels(fragment: str, config: Config) -> list[tuple[int, str]]:
    """Every intensity modifier present in `fragment`, as (level, term).

    Runs against the raw fragment, deliberately independent of keyword
    consumption, so a term that is both a category noun and a modifier
    ("bloody", "disturbing", "sadistic") counts as both.
    """
    found: list[tuple[int, str]] = []
    for level, terms in config.intensity.items():
        for term in terms:
            if re.search(rf"\b{re.escape(term)}\b", fragment, re.IGNORECASE):
                found.append((level, term))
    return found


def _match_categories(fragment: str, config: Config) -> list[tuple[str, str]]:
    """Categories named in `fragment`, as (category, matched keyword).

    Longest-first and consuming: once "disturbing images" matches, its span is
    blanked out so the shorter "disturbing" keyword cannot double-count it
    under a second category.
    """
    working = fragment.lower()
    hits: list[tuple[str, str]] = []
    for keyword, category in config.keywords:
        pattern = re.compile(rf"\b{re.escape(keyword)}\b")
        if pattern.search(working):
            working = pattern.sub(lambda m: " " * len(m.group()), working)
            hits.append((category, keyword))
    return hits


def parse(reason: str | None, config: Config) -> SeverityVector:
    """Parse an MPA reason string into a severity vector."""
    categories = config.category_names
    unknown_scores: dict[str, int | None] = {cat: None for cat in categories}

    if not reason or not reason.strip():
        return SeverityVector(
            raw=reason, parsed=False, scores=unknown_scores, evidence={}, unmatched=[]
        )

    body = _strip_prefix(reason, config).rstrip(". ")

    scores: dict[str, int | None] = {cat: 0 for cat in categories}
    evidence: dict[str, list[str]] = {cat: [] for cat in categories}
    unmatched: list[str] = []
    matched_any = False

    for segment in _SEGMENT_SPLIT.split(body):
        if not segment.strip():
            continue

        # Leading modifier of the segment, used when a later conjunction
        # fragment carries none of its own ("some violence and gore").
        segment_mods = _modifier_levels(segment, config)
        inherited = segment_mods[0][0] if segment_mods else None

        for fragment in _FRAGMENT_SPLIT.split(segment):
            fragment = fragment.strip()
            if not fragment:
                continue

            hits = _match_categories(fragment, config)
            if not hits:
                unmatched.append(fragment)
                continue

            matched_any = True
            own_mods = _modifier_levels(fragment, config)
            if own_mods:
                level = max(level for level, _ in own_mods)
            elif config.inherit_modifiers and inherited is not None:
                level = inherited
            else:
                level = config.default_level

            for category, _keyword in hits:
                current = scores[category] or 0
                scores[category] = max(current, level)
                evidence[category].append(fragment)

    if not matched_any:
        # Present but illegible. Unknown, not clean.
        return SeverityVector(
            raw=reason, parsed=False, scores=unknown_scores, evidence={}, unmatched=unmatched
        )

    return SeverityVector(
        raw=reason,
        parsed=True,
        scores=scores,
        evidence={cat: frags for cat, frags in evidence.items() if frags},
        unmatched=unmatched,
    )


@dataclass(frozen=True)
class Flag:
    category: str
    score: int | None
    threshold: int | None
    reason: str
    evidence: list[str]


@dataclass(frozen=True)
class Evaluation:
    """The display's verdict for one title."""

    flagged: bool
    flags: list[Flag]
    unknown_categories: list[str]
    vector: SeverityVector

    @property
    def has_unknowns(self) -> bool:
        return bool(self.unknown_categories)


def evaluate(
    vector: SeverityVector,
    config: Config,
    genres: list[str] | None = None,
) -> Evaluation:
    """Apply thresholds. Flagged means *greyed out*, never hidden."""
    genres = genres or []
    flags: list[Flag] = []

    for category, threshold in config.thresholds.items():
        if threshold is None:
            continue  # category displays a chip but never carries weight
        score = vector.scores.get(category)
        if score is None:
            continue  # unknown never flags on its own; surfaced separately
        if score >= threshold:
            flags.append(
                Flag(
                    category=category,
                    score=score,
                    threshold=threshold,
                    reason=f"{category} scored {score}, threshold is {threshold}",
                    evidence=vector.evidence.get(category, []),
                )
            )

    for genre in config.genre_flags:
        if genre.lower() in {g.lower() for g in genres}:
            flags.append(
                Flag(
                    category="genre",
                    score=None,
                    threshold=None,
                    reason=f"TMDB genre includes {genre}",
                    evidence=[genre],
                )
            )

    unknown = [cat for cat, score in vector.scores.items() if score is None]

    return Evaluation(
        flagged=bool(flags), flags=flags, unknown_categories=unknown, vector=vector
    )
