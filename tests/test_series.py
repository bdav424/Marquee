"""Tests for series/event tag resolution.

The feed's exact tag shape is not yet known, so these lock in the behaviour
that matters regardless of shape: recognised strands get their strong
treatment, unrecognised ones still badge, and nothing is silently dropped.
"""

import unittest
from pathlib import Path

from marquee.series import load_series_config, primary, resolve, unrecognised

CONFIG = load_series_config(Path(__file__).resolve().parent.parent / "config" / "series.toml")


class TestRecognisedStrands(unittest.TestCase):
    def test_terror_tuesday_gets_its_own_treatment(self):
        t = primary("Terror Tuesday", CONFIG)
        self.assertEqual(t.key, "terror_tuesday")
        self.assertEqual(t.background, "#8B0000")
        self.assertTrue(t.one_night)
        self.assertTrue(t.recognised)

    def test_matching_is_case_and_punctuation_insensitive(self):
        for variant in ("WEIRD WEDNESDAY", "weird-wednesday", "Weird  Wednesday!"):
            self.assertEqual(primary(variant, CONFIG).key, "weird_wednesday")

    def test_tag_embedded_in_a_longer_string_still_matches(self):
        t = primary("Alamo Presents: Terror Tuesday — 35mm", CONFIG)
        self.assertEqual(t.key, "terror_tuesday")

    def test_twenty_one_plus_survives_normalisation(self):
        self.assertEqual(primary("21+", CONFIG).key, "adults_only")


class TestMatchPrecedence(unittest.TestCase):
    def test_longer_pattern_wins_over_shorter(self):
        # "movie party" must not be claimed by the bare "party" pattern.
        self.assertEqual(primary("Movie Party", CONFIG).key, "movie_party")

    def test_pattern_does_not_match_inside_a_longer_word(self):
        # Guards the whole-word rule: a short pattern must not be swallowed by
        # an unrelated word that merely contains its letters.
        for innocent in ("Prepare for Battle", "Represent!", "Classicist Night"):
            t = primary(innocent, CONFIG)
            self.assertFalse(
                t.recognised, f"{innocent!r} should not match a configured strand"
            )

    def test_highest_priority_tag_becomes_primary(self):
        tags = ["Movie Party", "Terror Tuesday"]
        self.assertEqual(primary(tags, CONFIG).key, "terror_tuesday")

    def test_all_tags_are_retained_not_just_the_primary(self):
        resolved = resolve(["Movie Party", "21+"], CONFIG)
        self.assertEqual([t.key for t in resolved], ["movie_party", "adults_only"])

    def test_duplicate_tags_collapse(self):
        resolved = resolve(["Terror Tuesday", "terror tuesday"], CONFIG)
        self.assertEqual(len(resolved), 1)


class TestUnrecognisedStrands(unittest.TestCase):
    def test_unknown_strand_still_badges(self):
        t = primary("Cursed Film Club", CONFIG)
        self.assertIsNotNone(t)
        self.assertFalse(t.recognised)
        self.assertEqual(t.label, "CURSED FILM CLUB")
        self.assertEqual(t.background, CONFIG.default.background)

    def test_unknown_strand_is_reported_for_reconciliation(self):
        self.assertEqual(unrecognised("Cursed Film Club", CONFIG), ["Cursed Film Club"])

    def test_recognised_strand_is_not_reported(self):
        self.assertEqual(unrecognised("Terror Tuesday", CONFIG), [])


class TestNoTag(unittest.TestCase):
    def test_absent_tag_resolves_to_nothing(self):
        for empty in (None, "", "   ", []):
            self.assertEqual(resolve(empty, CONFIG), [])
            self.assertIsNone(primary(empty, CONFIG))

    def test_blank_entries_are_skipped_not_badged(self):
        self.assertEqual(resolve(["", "  "], CONFIG), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
