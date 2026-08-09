"""Turn a Snapshot into the JSON the display and widget read.

This is the only place severity, series treatment, and schedule data are
combined. The display never computes a verdict itself — it renders one — so
the widget and the companion page cannot disagree about whether a title is
greyed.

Run offline, at the end of a fetch cycle. The display reads the emitted file
and never touches the network at render.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from marquee.adapters.filmratings import strip_decoration
from marquee.model import Snapshot, Title
from marquee.reasons import predates_descriptors
from marquee.series import SeriesConfig, resolve
from marquee.severity import Config, evaluate, parse


def _treatment_json(treatment) -> dict:
    return {
        "key": treatment.key,
        "label": treatment.label,
        "background": treatment.background,
        "foreground": treatment.foreground,
        "one_night": treatment.one_night,
        "recognised": treatment.recognised,
    }


def build_title(
    title: Title, severity_config: Config, series_config: SeriesConfig
) -> dict:
    vector = parse(title.mpa_reason, severity_config)
    verdict = evaluate(vector, severity_config, title.genres)
    treatments = resolve(title.series_tags, series_config)

    return {
        "slug": title.slug,
        # Verbatim, for the drill-in panel.
        "name": title.name,
        # The film without Alamo's booking decoration, for surfaces with a
        # character budget. "Psycho Cinema Presents: Mystery Meat" spent a
        # whole board row on the strand, which the colour strip already shows.
        "display_name": strip_decoration(title.name),
        "rating": title.mpa_rating,
        # Verbatim, for the drill-in panel. Never paraphrased.
        "rating_reason": title.mpa_reason,
        "runtime_minutes": title.runtime_minutes,
        "release_year": title.release_year,
        # A question mark on a pre-1990 film is permanent, not a backlog item:
        # CARA did not issue descriptors then. The panel says which it is.
        "reason_unobtainable": predates_descriptors(title.release_year),
        "genres": title.genres,
        "synopsis": title.synopsis,
        "poster": title.poster,
        # The verdict. `flagged` means greyed, never hidden.
        "flagged": verdict.flagged,
        "flags": [
            {
                "category": f.category,
                "score": f.score,
                "threshold": f.threshold,
                "reason": f.reason,
                "evidence": f.evidence,
            }
            for f in verdict.flags
        ],
        # null in this map means unknown, distinct from 0 meaning clean.
        "severity": vector.scores,
        "unknown_categories": verdict.unknown_categories,
        "reason_parsed": vector.parsed,
        "series": _treatment_json(treatments[0]) if treatments else None,
        "series_secondary": [_treatment_json(t) for t in treatments[1:]],
        "showings": [
            {
                "showtime": s.showtime.isoformat(),
                "format": s.format,
                "auditorium": s.auditorium,
                "sold_out": s.sold_out,
            }
            for s in sorted(title.showings, key=lambda s: s.showtime)
        ],
    }


# Sorted after everything that has a showtime.
_NO_SHOWINGS = datetime.max.replace(tzinfo=timezone.utc)


def _first_showtime(title: Title) -> datetime:
    """The instant of a title's earliest showing, for ordering.

    Naive datetimes are read as UTC rather than allowed to raise: the model
    says showtimes are aware, and a crash in the builder would take the whole
    display down over a detail that only affects sort order.
    """
    times = [
        s.showtime if s.showtime.tzinfo else s.showtime.replace(tzinfo=timezone.utc)
        for s in title.showings
    ]
    return min(times, default=_NO_SHOWINGS)


def build_snapshot(
    snapshot: Snapshot, severity_config: Config, series_config: SeriesConfig
) -> dict:
    # The source Title is kept alongside its payload so ordering can use real
    # datetimes rather than their serialised form.
    built = [
        (t, build_title(t, severity_config, series_config)) for t in snapshot.titles
    ]

    # Step 5's parse-failure logging: what the vocabulary missed this cycle.
    unmatched_fragments: Counter = Counter()
    unparsed_reasons: list[dict] = []
    for title in snapshot.titles:
        vector = parse(title.mpa_reason, severity_config)
        unmatched_fragments.update(f.lower() for f in vector.unmatched)
        if title.mpa_reason and not vector.parsed:
            unparsed_reasons.append({"title": title.name, "reason": title.mpa_reason})

    unrecognised_series: Counter = Counter()
    for title in snapshot.titles:
        for treatment in resolve(title.series_tags, series_config):
            if not treatment.recognised and treatment.source:
                unrecognised_series[treatment.source] += 1

    # Sort: one-night programming first — it is the perishable half of the
    # schedule — then by earliest showtime.
    #
    # Ordered on the instant, not on the ISO text. Winchester's clocks change
    # in November, so two showings on the same date can carry different UTC
    # offsets, and comparing the strings then puts the later one first.
    def sort_key(pair):
        source, entry = pair
        one_night = bool(entry["series"] and entry["series"]["one_night"])
        return (0 if one_night else 1, _first_showtime(source))

    built.sort(key=sort_key)
    titles = [entry for _, entry in built]

    return {
        "theater": snapshot.theater,
        "fetched_at": snapshot.fetched_at.isoformat(),
        "generated_at": datetime.now().astimezone().isoformat(),
        "stale": snapshot.stale,
        # Echoed so the drill-in panel can show the rule alongside the score,
        # and so a config change is visible in the UI without a code change.
        # null means the category never flags.
        "thresholds": dict(severity_config.thresholds),
        "categories": severity_config.category_names,
        "titles": titles,
        "diagnostics": {
            "title_count": len(titles),
            "flagged_count": sum(1 for t in titles if t["flagged"]),
            "unknown_reason_count": sum(1 for t in titles if not t["reason_parsed"]),
            # Extend config/marquee.toml [categories] from this list.
            "unmatched_reason_fragments": unmatched_fragments.most_common(),
            "unparsed_reason_strings": unparsed_reasons,
            # Extend config/series.toml from this list.
            "unrecognised_series": unrecognised_series.most_common(),
        },
    }


def write_snapshot(payload: dict, path: Path | str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Atomic replace so the display never reads a half-written file.
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    tmp.replace(path)
    return path
