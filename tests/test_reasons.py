"""Tests for the hand-kept rating-reason book.

Every automatic source for MPA reason text is closed, so this file is the
content signal's only real input. It has to match titles however Alamo
decorates them, and it has to fail soft: a typo in the TOML must leave titles
`unknown`, not take the fetch down.
"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from marquee.reasons import load, lookup, normalise, stub_for

SHIPPED = load()


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

    def test_normalise_is_stable(self):
        self.assertEqual(normalise("The Long Dark"), normalise("the  long dark"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
