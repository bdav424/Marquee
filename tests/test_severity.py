"""Tests for the MPA rating-reason severity parser.

Reason strings below are real-world MPA phrasings (or close paraphrases of
them). They are the regression surface: when the parser mis-reads a new
string in production, add it here first.
"""

import unittest
from pathlib import Path

from marquee.severity import evaluate, load_config, parse

CONFIG = load_config(Path(__file__).resolve().parent.parent / "config" / "marquee.toml")


def vec(reason):
    return parse(reason, CONFIG)


class TestIntensityLadder(unittest.TestCase):
    def test_bare_noun_is_moderate(self):
        self.assertEqual(vec("Rated R for violence.").score("violence"), 2)

    def test_level_one_modifier(self):
        self.assertEqual(vec("Rated PG-13 for brief nudity.").score("sexual"), 1)

    def test_level_three_modifier(self):
        self.assertEqual(vec("Rated R for strong violence.").score("violence"), 3)

    def test_modifier_after_the_noun(self):
        # "throughout" trails its category noun rather than leading it.
        self.assertEqual(vec("Rated R for language throughout.").score("language"), 3)

    def test_dual_role_term_counts_as_modifier_and_keyword(self):
        # "bloody" is both a violence keyword and a level-3 modifier.
        self.assertEqual(vec("Rated R for bloody violence.").score("violence"), 3)

    def test_highest_modifier_in_fragment_wins(self):
        self.assertEqual(vec("Rated R for brief strong language.").score("language"), 3)


class TestClauseScoping(unittest.TestCase):
    def test_modifier_does_not_leak_across_clauses(self):
        v = vec(
            "Rated R for strong bloody violence, language throughout, "
            "and some sexual content."
        )
        self.assertEqual(v.score("violence"), 3)
        self.assertEqual(v.score("language"), 3)
        self.assertEqual(v.score("sexual"), 1)

    def test_conjunction_inherits_leading_modifier(self):
        # "some" distributes across "violence and gore"; both are violence.
        self.assertEqual(vec("Rated PG-13 for some violence and gore.").score("violence"), 1)

    def test_unmentioned_category_is_clean_not_unknown(self):
        v = vec("Rated R for strong violence.")
        self.assertEqual(v.score("sexual"), 0)
        self.assertFalse(v.is_unknown("sexual"))


class TestLongestMatchWins(unittest.TestCase):
    def test_disturbing_images_is_violence_not_frightening(self):
        v = vec("Rated R for disturbing images.")
        self.assertEqual(v.score("violence"), 3)  # "disturbing" also scores it 3
        self.assertEqual(v.score("frightening"), 0)

    def test_sexual_content_does_not_leak_into_other_categories(self):
        v = vec("Rated R for sexual content.")
        self.assertEqual(v.score("sexual"), 2)
        self.assertEqual(v.score("language"), 0)


class TestUnknownHandling(unittest.TestCase):
    def test_missing_string_is_unknown_everywhere(self):
        for missing in (None, "", "   "):
            v = vec(missing)
            self.assertFalse(v.parsed)
            self.assertTrue(all(v.is_unknown(c) for c in CONFIG.category_names))

    def test_unrecognisable_string_is_unknown_not_clean(self):
        v = vec("Rated PG for rude gestures and questionable haircuts.")
        self.assertFalse(v.parsed)
        self.assertTrue(v.is_unknown("violence"))
        self.assertNotEqual(v.score("violence"), 0)

    def test_unmatched_fragments_are_captured_for_extension(self):
        v = vec("Rated PG-13 for sci-fi action and thematic elements.")
        self.assertIn("thematic elements", [f.lower() for f in v.unmatched])

    def test_unknown_never_flags_on_its_own(self):
        result = evaluate(vec(None), CONFIG)
        self.assertFalse(result.flagged)
        self.assertTrue(result.has_unknowns)


class TestThresholds(unittest.TestCase):
    def test_brief_nudity_flags(self):
        # sexual >= 1, including "brief".
        result = evaluate(vec("Rated PG-13 for brief nudity."), CONFIG)
        self.assertTrue(result.flagged)
        self.assertEqual([f.category for f in result.flags], ["sexual"])

    def test_moderate_violence_does_not_flag(self):
        result = evaluate(vec("Rated PG-13 for violence."), CONFIG)
        self.assertFalse(result.flagged)

    def test_sadistic_violence_flags(self):
        result = evaluate(vec("Rated R for sadistic torture."), CONFIG)
        self.assertTrue(result.flagged)
        self.assertIn("violence", [f.category for f in result.flags])

    def test_language_never_flags_however_severe(self):
        result = evaluate(vec("Rated R for pervasive language."), CONFIG)
        self.assertFalse(result.flagged)

    def test_horror_genre_flags_without_any_reason_string(self):
        result = evaluate(vec(None), CONFIG, genres=["Horror", "Thriller"])
        self.assertTrue(result.flagged)
        self.assertEqual([f.category for f in result.flags], ["genre"])

    def test_frightening_moderate_flags(self):
        result = evaluate(vec("Rated PG-13 for terror."), CONFIG)
        self.assertTrue(result.flagged)

    def test_clean_title_does_not_flag(self):
        result = evaluate(vec("Rated PG for mild thematic elements and smoking."), CONFIG)
        self.assertFalse(result.flagged)


class TestProvenance(unittest.TestCase):
    def test_evidence_traces_back_to_the_fragment(self):
        v = vec("Rated R for strong bloody violence and some sexual content.")
        self.assertTrue(any("violence" in e for e in v.evidence["violence"]))

    def test_raw_string_is_preserved_verbatim_for_the_panel(self):
        raw = "Rated R for strong bloody violence."
        self.assertEqual(vec(raw).raw, raw)

    def test_flag_carries_threshold_and_evidence(self):
        result = evaluate(vec("Rated R for graphic nudity."), CONFIG)
        flag = result.flags[0]
        self.assertEqual(flag.category, "sexual")
        self.assertEqual(flag.threshold, 1)
        self.assertTrue(flag.evidence)


if __name__ == "__main__":
    unittest.main(verbosity=2)
