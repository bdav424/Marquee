"""Tests for the filmratings.com (CARA) rating-reason adapter.

Nothing here touches the network. What is tested is the part that decides
correctness: extraction from response text, title cleanup before searching,
and the cache policy that keeps a 6-hour cron from hammering a small public
lookup service.

Extraction itself has never been run against a live filmratings.com response,
so these fixtures are realistic markup rather than captured markup.
"""

import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from marquee.adapters.filmratings import (
    Reason,
    ReasonCache,
    extract_reason,
    extract_reason_for,
    normalise_title,
    strip_decoration,
)

# A CARA search returns every film whose name contains the query, each with
# its own reason. Attributing the wrong row to our film is the worst failure
# this adapter can produce: a confident, explained, incorrect verdict.
RESULTS_PAGE = '''
<table>
 <tr><td class="title">BRAND NEW DAY</td>
     <td class="rating">Rated R for pervasive language, drug use, and sexual
     content/nudity.</td></tr>
 <tr><td class="title">SPIDER-MAN: BRAND NEW DAY</td>
     <td class="rating">Rated PG-13 for sequences of action and violence.</td></tr>
 <tr><td class="title">A BRAND NEW DAY FOR US</td>
     <td class="rating">Rated G for general audiences.</td></tr>
</table>
'''


class TestResultVerification(unittest.TestCase):
    def test_picks_the_row_belonging_to_the_film(self):
        cert, reason = extract_reason_for(RESULTS_PAGE, "Spider-Man: Brand New Day")
        self.assertEqual(cert, "PG-13")
        self.assertIn("sequences of action", reason)

    def test_does_not_take_the_first_reason_on_the_page(self):
        # Regression: the naive extractor returned the R-rated stranger above.
        _, reason = extract_reason_for(RESULTS_PAGE, "Spider-Man: Brand New Day")
        self.assertNotIn("pervasive language", reason)

    def test_certification_mismatch_is_rejected(self):
        # Alamo says PG-13; a row claiming R is not our film.
        self.assertEqual(
            extract_reason_for(RESULTS_PAGE, "Spider-Man: Brand New Day", "R"),
            (None, None),
        )

    def test_certification_agreement_is_accepted(self):
        cert, reason = extract_reason_for(
            RESULTS_PAGE, "Spider-Man: Brand New Day", "PG-13"
        )
        self.assertIsNotNone(reason)

    def test_film_absent_from_results_yields_nothing(self):
        self.assertEqual(extract_reason_for(RESULTS_PAGE, "Ironwood"), (None, None))

    def test_shorter_title_still_matches_its_own_row(self):
        cert, reason = extract_reason_for(RESULTS_PAGE, "Brand New Day")
        self.assertEqual(cert, "R")

    def test_empty_title_yields_nothing(self):
        self.assertEqual(extract_reason_for(RESULTS_PAGE, ""), (None, None))


class TestExtraction(unittest.TestCase):
    def test_reads_reason_out_of_a_table_cell(self):
        cert, reason = extract_reason(
            "<td>Rated R for strong bloody violence, language throughout, "
            "and some sexual content.</td>"
        )
        self.assertEqual(cert, "R")
        self.assertIn("strong bloody violence", reason)

    def test_reads_reason_out_of_json(self):
        cert, reason = extract_reason(
            '{"rating":"Rated PG-13 for sequences of violence and action"}'
        )
        self.assertEqual(cert, "PG-13")
        self.assertTrue(reason.endswith("."))

    def test_output_is_shaped_for_the_severity_parser(self):
        # The parser strips a "Rated X for" lead-in, so emit one.
        _, reason = extract_reason("<p>Rated R for pervasive language.</p>")
        self.assertTrue(reason.lower().startswith("rated r for"))

    def test_bare_reason_without_lead_in(self):
        cert, reason = extract_reason(
            "<div>Rating Reason: some thematic elements and brief language</div>"
        )
        self.assertIsNone(cert)
        self.assertEqual(reason, "some thematic elements and brief language")

    def test_whitespace_and_newlines_are_collapsed(self):
        _, reason = extract_reason("Rated R for   strong\n  violence.")
        self.assertEqual(reason, "Rated R for strong violence.")

    def test_pg13_is_not_truncated_to_pg(self):
        cert, _ = extract_reason("Rated PG-13 for thematic elements.")
        self.assertEqual(cert, "PG-13")

    def test_no_match_returns_nothing_rather_than_guessing(self):
        # An unreadable page must leave the title unknown, never fabricate.
        for junk in ("<p>Nothing useful</p>", "", "404 Not Found"):
            self.assertEqual(extract_reason(junk), (None, None))

    def test_does_not_run_past_the_enclosing_tag(self):
        _, reason = extract_reason(
            "<td>Rated R for violence</td><td>UNRELATED COLUMN</td>"
        )
        self.assertNotIn("UNRELATED", reason)


class TestTitleCleanup(unittest.TestCase):
    def test_strips_alamo_programming_prefix(self):
        self.assertEqual(strip_decoration("Terror Tuesday: The Thing"), "The Thing")

    def test_strips_format_suffix(self):
        self.assertEqual(strip_decoration("The Long Dark - 35mm"), "The Long Dark")

    def test_strips_trailing_year(self):
        self.assertEqual(strip_decoration("Jaws (1975)"), "Jaws")

    def test_leaves_a_plain_title_alone(self):
        self.assertEqual(strip_decoration("Ironwood"), "Ironwood")

    def test_does_not_eat_a_colon_that_is_part_of_the_title(self):
        # Regression: a generic "word colon" rule turned
        # "Spider-Man: Brand New Day" into "Brand New Day" and searched CARA
        # for a different film.
        for real in ("Spider-Man: Brand New Day", "Mission: Impossible",
                     "Blade Runner 2049: The Final Cut"):
            self.assertEqual(strip_decoration(real), real)

    def test_never_strips_a_title_to_nothing(self):
        self.assertTrue(strip_decoration("Movie Party: "))

    def test_normalise_ignores_articles_and_punctuation(self):
        self.assertEqual(normalise_title("The Thing!"), normalise_title("Thing"))


class TestCachePolicy(unittest.TestCase):
    def setUp(self):
        self.dir = TemporaryDirectory()
        self.path = Path(self.dir.name) / "reasons.json"

    def tearDown(self):
        self.dir.cleanup()

    def test_hit_is_stored_and_returned(self):
        cache = ReasonCache(self.path)
        cache.put("The Thing", Reason("R", "Rated R for gore.", "test"))
        self.assertEqual(cache.get("The Thing").reason, "Rated R for gore.")

    def test_hit_survives_a_reload(self):
        cache = ReasonCache(self.path)
        cache.put("The Thing", Reason("R", "Rated R for gore.", "test"))
        cache.save()
        self.assertEqual(ReasonCache(self.path).get("The Thing").reason,
                         "Rated R for gore.")

    def test_lookup_is_insensitive_to_alamo_decoration(self):
        cache = ReasonCache(self.path)
        cache.put("The Thing", Reason("R", "Rated R for gore.", "test"))
        self.assertIsNotNone(cache.get("the thing"))

    def test_fresh_miss_is_remembered_so_we_do_not_re_ask(self):
        cache = ReasonCache(self.path)
        cache.put("Obscure Film", Reason(None, None, "filmratings.com"))
        self.assertIsNotNone(cache.get("Obscure Film"))

    def test_stale_miss_expires_so_late_additions_are_found(self):
        cache = ReasonCache(self.path)
        cache.put("Obscure Film", Reason(None, None, "filmratings.com"))
        key = normalise_title("Obscure Film")
        cache.entries[key]["checked_at"] = (
            datetime.now(timezone.utc) - timedelta(days=30)
        ).isoformat()
        self.assertIsNone(cache.get("Obscure Film"))

    def test_a_hit_never_expires(self):
        cache = ReasonCache(self.path)
        cache.put("Old Film", Reason("R", "Rated R for violence.", "test"))
        key = normalise_title("Old Film")
        cache.entries[key]["checked_at"] = (
            datetime.now(timezone.utc) - timedelta(days=3650)
        ).isoformat()
        self.assertIsNotNone(cache.get("Old Film"))

    def test_corrupt_cache_file_does_not_crash_the_cycle(self):
        self.path.write_text("{ this is not json")
        self.assertEqual(ReasonCache(self.path).entries, {})

    def test_unknown_title_is_a_miss(self):
        self.assertIsNone(ReasonCache(self.path).get("Never Seen"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
