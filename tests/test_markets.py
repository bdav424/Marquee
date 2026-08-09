"""Tests for the market list.

This is the config that turns a one-theatre display into a several-theatre
one without turning it into a listings site. Two things matter: it fails soft
like the rest of the config layer, and it can never point the page at a
snapshot that does not exist.
"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from marquee.adapters.alamo import market_name, schedule_url
from marquee.markets import FALLBACK_SLUG, load, snapshot_name


class TestLoading(unittest.TestCase):
    def setUp(self):
        self.dir = TemporaryDirectory()
        self.path = Path(self.dir.name) / "markets.toml"

    def tearDown(self):
        self.dir.cleanup()

    def write(self, text):
        self.path.write_text(text)
        return load(self.path)

    def test_reads_slugs_and_names(self):
        config = self.write(
            'default = "winchester"\n'
            '[[market]]\nslug = "winchester"\nname = "Winchester, VA"\n'
            '[[market]]\nslug = "raleigh"\nname = "Raleigh, NC"\n'
        )
        self.assertEqual([m.slug for m in config.markets], ["winchester", "raleigh"])
        self.assertEqual(config.default_market.name, "Winchester, VA")

    def test_slugs_are_lowercased(self):
        config = self.write('[[market]]\nslug = "Raleigh"\n')
        self.assertEqual(config.markets[0].slug, "raleigh")

    def test_a_missing_name_falls_back_to_the_slug(self):
        self.assertEqual(self.write('[[market]]\nslug = "raleigh"\n').markets[0].name,
                         "raleigh")

    def test_duplicate_slugs_are_collapsed(self):
        # Otherwise the same board builds twice and the picker shows two
        # identical rows.
        config = self.write(
            '[[market]]\nslug = "raleigh"\n[[market]]\nslug = "raleigh"\n'
        )
        self.assertEqual(len(config.markets), 1)

    def test_a_default_naming_an_unbuilt_market_falls_back(self):
        # Otherwise the page opens on a file that was never written.
        config = self.write(
            'default = "denver"\n[[market]]\nslug = "raleigh"\n'
        )
        self.assertEqual(config.default, "raleigh")

    def test_get_finds_by_slug(self):
        config = self.write('[[market]]\nslug = "raleigh"\nname = "Raleigh, NC"\n')
        self.assertEqual(config.get("raleigh").name, "Raleigh, NC")
        self.assertIsNone(config.get("nowhere"))


class TestFailsSoft(unittest.TestCase):
    def setUp(self):
        self.dir = TemporaryDirectory()
        self.path = Path(self.dir.name) / "markets.toml"

    def tearDown(self):
        self.dir.cleanup()

    def assertIsFallback(self, config):
        self.assertEqual([m.slug for m in config.markets], [FALLBACK_SLUG])
        self.assertEqual(config.default, FALLBACK_SLUG)

    def test_missing_file(self):
        self.assertIsFallback(load(self.path))

    def test_malformed_toml(self):
        self.path.write_text("[[market\nslug =")
        self.assertIsFallback(load(self.path))

    def test_empty_market_list(self):
        self.path.write_text('default = "raleigh"\n')
        self.assertIsFallback(load(self.path))

    def test_entries_with_no_slug_are_skipped(self):
        self.path.write_text('[[market]]\nname = "Nameless"\n')
        self.assertIsFallback(load(self.path))


class TestShippedFile(unittest.TestCase):
    def test_the_shipped_list_is_winchester(self):
        # The project is one theatre's marquee and opens on that theatre.
        config = load()
        self.assertEqual(config.default, "winchester")
        self.assertIn("winchester", [m.slug for m in config.markets])


class TestUrls(unittest.TestCase):
    def test_the_slug_is_the_only_thing_that_varies(self):
        self.assertEqual(
            schedule_url("raleigh"),
            "https://drafthouse.com/s/mother/v2/schedule/market/raleigh",
        )

    def test_the_default_is_winchester(self):
        self.assertTrue(schedule_url().endswith("/winchester"))

    def test_snapshot_names_are_per_market(self):
        self.assertEqual(snapshot_name("raleigh"), "raleigh.json")


class TestMarketName(unittest.TestCase):
    """Alamo's own wording beats a title-cased slug."""

    def test_reads_the_feed_name(self):
        payload = {"data": {"market": [{"slug": "winchester",
                                        "name": "Winchester, VA"}]}}
        self.assertEqual(market_name(payload), "Winchester, VA")

    def test_absent_market_block_is_none(self):
        self.assertIsNone(market_name({"data": {}}))

    def test_junk_payload_does_not_raise(self):
        for junk in (None, [], "text", {"data": "text"}, {"data": {"market": [1]}}):
            self.assertIsNone(market_name(junk))


if __name__ == "__main__":
    unittest.main(verbosity=2)
