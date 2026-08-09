"""Tests for the hand-kept rating-reason book.

Every automatic source for MPA reason text is closed, so this file is the
content signal's only real input. It has to match titles however Alamo
decorates them, and it has to fail soft: a typo in the TOML must leave titles
`unknown`, not take the fetch down.
"""

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from marquee.reasons import (
    is_exempt, load, load_exempt, lookup, normalise, stub_for,
)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from build_sample import SAMPLE_TITLES as _SAMPLE  # noqa: E402

SAMPLE_TITLES = [t.name for t in _SAMPLE]

SHIPPED = load()
SHIPPED_EXEMPT = load_exempt()


class TestMatching(unittest.TestCase):
    def setUp(self):
        self.dir = TemporaryDirectory()
        self.path = Path(self.dir.name) / "reasons.toml"
        self.path.write_text(
            '[reasons]\n'
            '"The Thing" = "Rated R for gore."\n'
            '"Spider-Man: Brand New Day" = "Rated PG-13 for action."\n'
        )
        self.book = load(self.path)

    def tearDown(self):
        self.dir.cleanup()

    def test_exact_title(self):
        self.assertEqual(lookup("The Thing", self.book), "Rated R for gore.")

    def test_case_and_punctuation_are_ignored(self):
        for variant in ("the thing", "THE THING", "The Thing!"):
            self.assertIsNotNone(lookup(variant, self.book))

    def test_leading_article_is_ignored(self):
        self.assertIsNotNone(lookup("Thing", self.book))

    def test_alamo_programming_prefix_is_stripped(self):
        # A strand should not need its own entry.
        self.assertIsNotNone(lookup("Terror Tuesday: The Thing", self.book))

    def test_format_suffix_is_stripped(self):
        self.assertIsNotNone(lookup("The Thing - 35mm", self.book))

    def test_trailing_year_is_stripped(self):
        self.assertIsNotNone(lookup("The Thing (1982)", self.book))

    def test_a_colon_inside_a_real_title_is_preserved(self):
        # Regression from the CARA adapter: a generic "word colon" rule ate
        # "Spider-Man:" and matched a different film.
        self.assertEqual(
            lookup("Spider-Man: Brand New Day", self.book),
            "Rated PG-13 for action.",
        )

    def test_unknown_title_returns_nothing(self):
        self.assertIsNone(lookup("Never Heard Of It", self.book))


class TestFailsSoft(unittest.TestCase):
    def setUp(self):
        self.dir = TemporaryDirectory()
        self.path = Path(self.dir.name) / "reasons.toml"

    def tearDown(self):
        self.dir.cleanup()

    def test_missing_file_is_an_empty_book(self):
        self.assertEqual(load(self.path), {})

    def test_malformed_toml_does_not_raise(self):
        # A typo must leave titles unknown, not abort the cycle.
        self.path.write_text("[reasons\nbroken = ")
        self.assertEqual(load(self.path), {})

    def test_blank_entries_are_skipped(self):
        # The generated stub writes empty strings for a human to fill in.
        self.path.write_text('[reasons]\n"Half Done" = ""\n"Done" = "Rated R for x."\n')
        book = load(self.path)
        self.assertIsNone(lookup("Half Done", book))
        self.assertIsNotNone(lookup("Done", book))

    def test_a_file_with_no_reasons_table_is_empty(self):
        self.path.write_text('[something_else]\nkey = "value"\n')
        self.assertEqual(load(self.path), {})


class TestNoDescriptor(unittest.TestCase):
    """Films that predate rating descriptors are not outstanding work."""

    def setUp(self):
        self.dir = TemporaryDirectory()
        self.path = Path(self.dir.name) / "reasons.toml"

    def tearDown(self):
        self.dir.cleanup()

    def test_listed_titles_are_exempt(self):
        self.path.write_text('no_descriptor = ["Taxi Driver"]\n[reasons]\n')
        exempt = load_exempt(self.path)
        self.assertTrue(is_exempt("Taxi Driver", exempt))
        self.assertTrue(is_exempt("taxi driver", exempt))

    def test_unlisted_titles_are_not(self):
        self.path.write_text('no_descriptor = ["Taxi Driver"]\n[reasons]\n')
        self.assertFalse(is_exempt("Toy Story 5", load_exempt(self.path)))

    def test_the_key_must_sit_above_the_reasons_table(self):
        # Regression. Written below [reasons] it silently becomes
        # reasons.no_descriptor and the exemption list reads as empty.
        below = 'no_descriptor = ["Taxi Driver"]\n[reasons]\n"X" = "Rated R for y."\n'
        self.path.write_text(below)
        self.assertEqual(len(load_exempt(self.path)), 1)

        self.path.write_text('[reasons]\n"X" = "Rated R for y."\nno_descriptor = ["Taxi Driver"]\n')
        self.assertEqual(load_exempt(self.path), set(),
                         "scoped into [reasons], so correctly not found")

    def test_a_list_under_reasons_is_not_mistaken_for_a_reason(self):
        self.path.write_text('[reasons]\nno_descriptor = ["Taxi Driver"]\n')
        self.assertEqual(load(self.path), {})

    def test_missing_file_exempts_nothing(self):
        self.assertEqual(load_exempt(self.path), set())

    def test_the_shipped_file_actually_exempts_its_entries(self):
        # The shipped file had this key below [reasons] and silently exempted
        # nothing; this fails if that regresses.
        self.assertGreater(len(SHIPPED_EXEMPT), 0)
        self.assertTrue(is_exempt("Taxi Driver", SHIPPED_EXEMPT))


class TestStub(unittest.TestCase):
    def test_stub_is_paste_ready_toml(self):
        text = stub_for(["Salt Flats", "Hydroplane"])
        self.assertIn('"Salt Flats" = ""', text)
        self.assertIn('"Hydroplane" = ""', text)

    def test_stub_says_not_to_paraphrase(self):
        # The parser reads the wording, so this instruction is load-bearing.
        self.assertIn("verbatim", stub_for(["X"]).lower())


class TestShippedFile(unittest.TestCase):
    def test_the_shipped_book_parses(self):
        self.assertIsInstance(SHIPPED, dict)

    def test_shipped_entries_are_shaped_for_the_parser(self):
        # The severity parser strips a "Rated X for" lead-in, so entries want
        # to carry one.
        for key, reason in SHIPPED.items():
            self.assertTrue(
                reason.lower().startswith("rated"),
                f"{key}: reason should begin with the MPA lead-in",
            )

    def test_no_invented_title_is_shipped(self):
        # The book shipped with two worked examples borrowed from
        # build_sample.py's fixtures. Those titles are invented, so their
        # reasons are too — and a fabricated sentence produces a confident
        # wrong verdict, which is the one outcome the content signal is meant
        # to rule out. Anything in here must be a sentence CARA actually
        # wrote about a film that actually exists.
        invented = {normalise(n) for n in SAMPLE_TITLES}
        self.assertEqual(invented & set(SHIPPED), set())

    def test_normalise_is_stable(self):
        self.assertEqual(normalise("The Long Dark"), normalise("the  long dark"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
