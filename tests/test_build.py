"""Tests for the display snapshot builder.

build.py is where severity, series treatment and schedule are combined into
the one verdict every surface renders. If it is wrong, the poster grid, the
split-flap board and the widget are all wrong together and none of them
disagree loudly enough to notice.

These lock in three things: that the payload keeps the shape the display
reads, that no title is ever dropped, and that the ordering is chronological
rather than merely alphabetical on a timestamp.
"""

import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from marquee.build import build_snapshot, build_title, write_snapshot
from marquee.model import Showing, Snapshot, Title
from marquee.series import load_series_config
from marquee.severity import load_config

SEVERITY = load_config()
SERIES = load_series_config()

EDT = timezone(timedelta(hours=-4))
EST = timezone(timedelta(hours=-5))


def at(day, hour, minute=0, tz=EDT):
    return datetime(2026, 8, day, hour, minute, tzinfo=tz)


def title(slug, name, **kw):
    kw.setdefault("showings", [Showing(at(10, 19))])
    return Title(slug=slug, name=name, **kw)


def build(*titles, stale=False):
    snap = Snapshot("Alamo Drafthouse Winchester", at(10, 9), list(titles), stale)
    return build_snapshot(snap, SEVERITY, SERIES)


class TestNothingIsDropped(unittest.TestCase):
    """The rule the whole display rests on."""

    def test_every_title_reaches_the_payload(self):
        payload = build(
            title("a", "Clean Film", mpa_reason="Rated PG for mild peril."),
            title("b", "Nasty Film", mpa_reason="Rated R for strong bloody violence."),
            title("c", "Unknown Film"),
        )
        self.assertEqual({t["slug"] for t in payload["titles"]}, {"a", "b", "c"})

    def test_a_flagged_title_is_present_and_marked_not_removed(self):
        payload = build(
            title("nasty", "Nasty", mpa_reason="Rated R for graphic nudity.")
        )
        self.assertEqual(len(payload["titles"]), 1)
        self.assertTrue(payload["titles"][0]["flagged"])

    def test_a_title_with_no_showings_is_still_carried(self):
        payload = build(title("quiet", "No Showtimes", showings=[]))
        self.assertEqual(len(payload["titles"]), 1)
        self.assertEqual(payload["titles"][0]["showings"], [])

    def test_empty_snapshot_builds_rather_than_raising(self):
        payload = build()
        self.assertEqual(payload["titles"], [])
        self.assertEqual(payload["diagnostics"]["title_count"], 0)


class TestPayloadContract(unittest.TestCase):
    """Keys the page, board and widget read by name."""

    TITLE_KEYS = {
        "slug", "name", "rating", "rating_reason", "runtime_minutes", "genres",
        "synopsis", "poster", "flagged", "flags", "severity",
        "unknown_categories", "reason_parsed", "series", "series_secondary",
        "showings",
    }

    def test_title_carries_every_key_the_display_reads(self):
        entry = build_title(
            title("x", "X", mpa_reason="Rated R for violence."), SEVERITY, SERIES
        )
        self.assertEqual(self.TITLE_KEYS - set(entry), set())

    def test_snapshot_carries_its_top_level_keys(self):
        payload = build(title("x", "X"))
        for key in ("theater", "fetched_at", "generated_at", "stale",
                    "thresholds", "categories", "titles", "diagnostics"):
            self.assertIn(key, payload)

    def test_thresholds_are_echoed_so_the_panel_can_show_the_rule(self):
        payload = build(title("x", "X"))
        self.assertEqual(payload["thresholds"]["sexual"], 1)
        # A category that never flags is carried as null, not omitted.
        self.assertIn("language", payload["thresholds"])
        self.assertIsNone(payload["thresholds"]["language"])

    def test_stale_flag_is_carried_through(self):
        self.assertTrue(build(title("x", "X"), stale=True)["stale"])

    def test_payload_is_json_serialisable(self):
        json.dumps(build(title("x", "X", mpa_reason="Rated R for gore.")))


class TestVerdict(unittest.TestCase):
    def test_unknown_severity_is_null_not_zero(self):
        # The distinction the entire content signal depends on.
        entry = build_title(title("u", "Unknown"), SEVERITY, SERIES)
        self.assertIsNone(entry["severity"]["violence"])
        self.assertFalse(entry["reason_parsed"])
        self.assertFalse(entry["flagged"])

    def test_clean_severity_is_zero_not_null(self):
        entry = build_title(
            title("c", "Clean", mpa_reason="Rated R for strong violence."),
            SEVERITY, SERIES,
        )
        self.assertEqual(entry["severity"]["sexual"], 0)
        self.assertTrue(entry["reason_parsed"])

    def test_flag_carries_its_working_for_the_panel(self):
        entry = build_title(
            title("f", "F", mpa_reason="Rated R for graphic nudity."),
            SEVERITY, SERIES,
        )
        flag = entry["flags"][0]
        self.assertEqual(flag["category"], "sexual")
        self.assertEqual(flag["threshold"], 1)
        self.assertTrue(flag["evidence"])

    def test_rating_reason_is_verbatim(self):
        raw = "Rated R for strong bloody violence, and some sexual content."
        entry = build_title(title("v", "V", mpa_reason=raw), SEVERITY, SERIES)
        self.assertEqual(entry["rating_reason"], raw)

    def test_horror_genre_flags_without_a_reason_string(self):
        entry = build_title(
            title("h", "Horror", genres=["Horror"]), SEVERITY, SERIES
        )
        self.assertTrue(entry["flagged"])
        self.assertEqual([f["category"] for f in entry["flags"]], ["genre"])

    def test_language_never_flags_however_severe(self):
        entry = build_title(
            title("l", "L", mpa_reason="Rated R for pervasive language."),
            SEVERITY, SERIES,
        )
        self.assertFalse(entry["flagged"])
        self.assertEqual(entry["severity"]["language"], 3)


class TestOrdering(unittest.TestCase):
    def test_showings_within_a_title_are_chronological(self):
        entry = build_title(
            title("s", "S", showings=[Showing(at(11, 14)), Showing(at(10, 20))]),
            SEVERITY, SERIES,
        )
        times = [s["showtime"] for s in entry["showings"]]
        self.assertEqual(times, sorted(times))

    def test_one_night_programming_sorts_ahead(self):
        payload = build(
            title("plain", "Plain", showings=[Showing(at(10, 12))]),
            title("terror", "Terror Film",
                  showings=[Showing(at(12, 22), series_tags=["Terror Tuesday"])]),
        )
        self.assertEqual(payload["titles"][0]["slug"], "terror")

    def test_titles_order_by_earliest_showing(self):
        payload = build(
            title("late", "Late", showings=[Showing(at(11, 9))]),
            title("early", "Early", showings=[Showing(at(10, 9))]),
        )
        self.assertEqual([t["slug"] for t in payload["titles"]], ["early", "late"])

    def test_ordering_is_chronological_across_a_dst_change(self):
        # Winchester's clocks go back in November, so two showings on the same
        # calendar day can carry different UTC offsets. Ordering on the ISO
        # text rather than the instant puts the later one first.
        earlier = datetime(2026, 11, 1, 1, 30, tzinfo=EDT)   # 05:30 UTC
        later = datetime(2026, 11, 1, 1, 0, tzinfo=EST)      # 06:00 UTC
        self.assertLess(earlier, later)

        payload = build(
            title("second", "Second", showings=[Showing(later)]),
            title("first", "First", showings=[Showing(earlier)]),
        )
        self.assertEqual([t["slug"] for t in payload["titles"]], ["first", "second"])


class TestDiagnostics(unittest.TestCase):
    def test_counts_reflect_the_payload(self):
        payload = build(
            title("a", "A", mpa_reason="Rated R for graphic nudity."),
            title("b", "B", mpa_reason="Rated PG for mild peril."),
            title("c", "C"),
        )
        d = payload["diagnostics"]
        self.assertEqual(d["title_count"], 3)
        self.assertEqual(d["flagged_count"], 1)
        self.assertEqual(d["unknown_reason_count"], 1)

    def test_unreadable_vocabulary_is_reported_for_extension(self):
        payload = build(
            title("x", "X", mpa_reason="Rated R for aberrant conduct.")
        )
        fragments = dict(payload["diagnostics"]["unmatched_reason_fragments"])
        self.assertIn("aberrant conduct", fragments)

    def test_a_wholly_unreadable_reason_is_reported_with_its_title(self):
        payload = build(
            title("x", "Odd Film", mpa_reason="Rated R for unsettling tableaux.")
        )
        reported = payload["diagnostics"]["unparsed_reason_strings"]
        self.assertEqual(reported[0]["title"], "Odd Film")

    def test_unconfigured_series_is_reported_but_still_badged(self):
        payload = build(
            title("x", "X", showings=[Showing(at(10, 20),
                                              series_tags=["Cursed Film Club"])])
        )
        self.assertEqual(
            dict(payload["diagnostics"]["unrecognised_series"]),
            {"Cursed Film Club": 1},
        )
        self.assertEqual(payload["titles"][0]["series"]["label"], "CURSED FILM CLUB")

    def test_a_clean_cycle_reports_no_gaps(self):
        payload = build(title("x", "X", mpa_reason="Rated R for strong violence."))
        d = payload["diagnostics"]
        self.assertEqual(d["unmatched_reason_fragments"], [])
        self.assertEqual(d["unparsed_reason_strings"], [])
        self.assertEqual(d["unrecognised_series"], [])


class TestWriteSnapshot(unittest.TestCase):
    def setUp(self):
        self.dir = TemporaryDirectory()
        self.path = Path(self.dir.name) / "nested" / "marquee.json"

    def tearDown(self):
        self.dir.cleanup()

    def test_creates_parent_directories(self):
        write_snapshot({"titles": []}, self.path)
        self.assertTrue(self.path.exists())

    def test_round_trips_as_json(self):
        payload = build(title("x", "X", mpa_reason="Rated R for gore."))
        write_snapshot(payload, self.path)
        self.assertEqual(json.loads(self.path.read_text())["titles"][0]["slug"], "x")

    def test_leaves_no_temp_file_behind(self):
        # The display polls this directory; a stray .tmp would be served.
        write_snapshot({"titles": []}, self.path)
        self.assertEqual([p.name for p in self.path.parent.iterdir()],
                         ["marquee.json"])

    def test_overwrite_replaces_rather_than_appends(self):
        write_snapshot({"titles": [1, 2, 3]}, self.path)
        write_snapshot({"titles": []}, self.path)
        self.assertEqual(json.loads(self.path.read_text()), {"titles": []})

    def test_non_ascii_survives_the_round_trip(self):
        write_snapshot({"theater": "Cinéma Ámbar"}, self.path)
        self.assertEqual(json.loads(self.path.read_text())["theater"], "Cinéma Ámbar")


if __name__ == "__main__":
    unittest.main(verbosity=2)
