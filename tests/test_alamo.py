"""Tests for the Alamo schedule adapter.

The fixture mirrors the real shape of
/s/mother/v2/schedule/market/winchester, taken from the live field inventory
captured 2026-08-08 — same keys, same slug-reference structure, same
naive-UTC/naive-local timestamp pair. Values are trimmed and partly invented,
but nothing here assumes a field the real payload does not have.
"""

import unittest
from datetime import timedelta, timezone

from marquee.adapters import alamo
from marquee.adapters.alamo import DiscoveryPending, to_titles

PAYLOAD = {
    "data": {
        "market": [{"slug": "winchester", "name": "Winchester, VA"}],
        "formats": [
            {"slug": "2d-digital", "title": "2D Digital"},
            {"slug": "35mm", "title": "35mm"},
        ],
        "agePolicies": [
            {"slug": "rated-pg-13", "name": "Rated PG-13 (Standard)"},
            {"slug": "rated-r", "name": "Rated R"},
            {"slug": "adult-focus", "name": "Rated PG with Adult Focus"},
        ],
        "presentationAttributes": [
            {"slug": "first-run", "name": "New Releases", "isUserVisible": True},
            {"slug": "terror-tuesday", "name": "Terror Tuesday", "isUserVisible": True},
            {"slug": "internal-thing", "name": "Internal", "isUserVisible": False},
        ],
        "presentations": [
            {
                "slug": "spider-man-brand-new-day",
                "isHidden": False,
                "presentationAttributeSlugs": ["first-run"],
                "primaryCollectionSlug": None,
                "event": None,
                "eventType": None,
                "superTitle": None,
                "show": {
                    "title": "Spider-Man: Brand New Day",
                    "certification": "PG-13",
                    "posterImages": [{"uri": "https://img/spidey.jpg"}],
                },
            },
            {
                "slug": "the-thing",
                "isHidden": False,
                "presentationAttributeSlugs": ["terror-tuesday", "internal-thing"],
                "superTitle": "Terror Tuesday",
                "show": {
                    "title": "The Thing",
                    "certification": "R",
                    "portraitHeroImage": {"uri": "https://img/thing.jpg"},
                },
            },
            {   # hidden -> must not appear
                "slug": "hidden-film",
                "isHidden": True,
                "show": {"title": "Hidden Film", "certification": "R"},
            },
            {   # no sessions -> not playing in this window
                "slug": "not-playing",
                "isHidden": False,
                "show": {"title": "Not Playing", "certification": "PG"},
            },
        ],
        "sessions": [
            {
                "sessionId": 1,
                "presentationSlug": "spider-man-brand-new-day",
                "showTimeClt": "2026-08-29T13:00:00",
                "showTimeUtc": "2026-08-29T17:00:00",
                "cinemaTimeZoneName": "America/New_York",
                "formatSlug": "2d-digital",
                "agePolicySlug": "rated-pg-13",
                "screenNumber": 7,
                "status": "ONSALE",
                "isHidden": False,
            },
            {
                "sessionId": 2,
                "presentationSlug": "spider-man-brand-new-day",
                "showTimeUtc": "2026-08-30T00:15:00",
                "cinemaTimeZoneName": "America/New_York",
                "formatSlug": "2d-digital",
                "agePolicySlug": "rated-pg-13",
                "screenNumber": 7,
                "status": "SOLDOUT",
                "isHidden": False,
            },
            {
                "sessionId": 3,
                "presentationSlug": "the-thing",
                "showTimeUtc": "2026-08-30T01:45:00",
                "cinemaTimeZoneName": "America/New_York",
                "formatSlug": "35mm",
                "agePolicySlug": "adult-focus",
                "screenNumber": 1,
                "status": "ONSALE",
                "isHidden": False,
            },
            {   # hidden -> must not appear
                "sessionId": 4,
                "presentationSlug": "the-thing",
                "showTimeUtc": "2026-08-31T01:45:00",
                "formatSlug": "35mm",
                "screenNumber": 1,
                "status": "ONSALE",
                "isHidden": True,
            },
            {   # orphan: no matching presentation
                "sessionId": 5,
                "presentationSlug": "ghost-film",
                "showTimeUtc": "2026-08-30T02:00:00",
                "formatSlug": "35mm",
                "screenNumber": 2,
                "status": "ONSALE",
                "isHidden": False,
            },
        ],
    }
}


def titles():
    return {t.slug: t for t in to_titles(PAYLOAD)}


class TestJoin(unittest.TestCase):
    def test_sessions_attach_to_their_presentation(self):
        t = titles()
        self.assertEqual(len(t["spider-man-brand-new-day"].showings), 2)
        self.assertEqual(len(t["the-thing"].showings), 1)

    def test_hidden_presentation_is_dropped(self):
        self.assertNotIn("hidden-film", titles())

    def test_hidden_session_is_dropped(self):
        # the-thing has two sessions in the feed; one is hidden.
        self.assertEqual(len(titles()["the-thing"].showings), 1)

    def test_presentation_with_no_sessions_is_dropped(self):
        self.assertNotIn("not-playing", titles())

    def test_orphan_session_does_not_invent_a_title(self):
        self.assertNotIn("ghost-film", titles())


class TestShowtimes(unittest.TestCase):
    def test_showtime_is_timezone_aware_in_cinema_zone(self):
        s = titles()["spider-man-brand-new-day"].showings[0]
        self.assertIsNotNone(s.showtime.tzinfo)
        # 17:00 UTC is 13:00 EDT — matches the feed's own showTimeClt.
        self.assertEqual(s.showtime.hour, 13)

    def test_utc_is_preferred_and_converted_not_taken_literally(self):
        s = titles()["spider-man-brand-new-day"].showings[0]
        self.assertEqual(s.showtime.astimezone(timezone.utc).hour, 17)

    def test_showings_sorted_and_late_night_lands_on_previous_evening(self):
        # 00:15 UTC on the 30th is 20:15 EDT on the 29th.
        s = titles()["spider-man-brand-new-day"].showings[1]
        self.assertEqual((s.showtime.day, s.showtime.hour), (29, 20))


class TestShowtimeOffsets(unittest.TestCase):
    """The offset is read off the feed, not looked up in a tz database."""

    @staticmethod
    def _session(clt, utc, **kw):
        return dict({"sessionId": 1, "showTimeClt": clt, "showTimeUtc": utc,
                     "cinemaTimeZoneName": "America/New_York"}, **kw)

    def test_offset_comes_from_the_clt_utc_pair(self):
        dt = alamo._showtime(self._session("2026-08-29T13:00:00",
                                           "2026-08-29T17:00:00"))
        self.assertEqual(dt.utcoffset(), timedelta(hours=-4))
        self.assertEqual(dt.hour, 13)

    def test_daylight_saving_is_handled_per_session(self):
        # Each session carries whatever offset applied on its own date, so
        # winter and summer come out right without any zone rules.
        winter = alamo._showtime(self._session("2026-12-05T19:30:00",
                                               "2026-12-06T00:30:00"))
        self.assertEqual(winter.utcoffset(), timedelta(hours=-5))

    def test_works_with_no_timezone_database_present(self):
        # Termux ships neither the IANA database nor the tzdata package, and
        # ZoneInfo raising there used to abort the whole fetch.
        original = alamo.ZoneInfo
        alamo.ZoneInfo = lambda key: (_ for _ in ()).throw(KeyError(key))
        try:
            dt = alamo._showtime(self._session("2026-08-29T13:00:00",
                                               "2026-08-29T17:00:00"))
            self.assertEqual(dt.utcoffset(), timedelta(hours=-4))
        finally:
            alamo.ZoneInfo = original

    def test_a_whole_payload_maps_without_a_timezone_database(self):
        original = alamo.ZoneInfo
        alamo.ZoneInfo = lambda key: (_ for _ in ()).throw(KeyError(key))
        try:
            self.assertEqual(len(to_titles(PAYLOAD)), 2)
        finally:
            alamo.ZoneInfo = original

    def test_seconds_of_offset_are_rounded_away(self):
        dt = alamo._showtime(self._session("2026-08-29T13:00:11",
                                           "2026-08-29T17:00:00"))
        self.assertEqual(dt.utcoffset().total_seconds() % 60, 0)

    def test_utc_alone_still_yields_an_aware_instant(self):
        dt = alamo._showtime({"sessionId": 2, "showTimeUtc": "2026-08-29T17:00:00"})
        self.assertIsNotNone(dt.tzinfo)
        self.assertEqual(dt.astimezone(timezone.utc).hour, 17)

    def test_local_alone_still_yields_an_aware_instant(self):
        dt = alamo._showtime({"sessionId": 3, "showTimeClt": "2026-08-29T13:00:00"})
        self.assertIsNotNone(dt.tzinfo)

    def test_neither_timestamp_raises(self):
        with self.assertRaises(DiscoveryPending):
            alamo._showtime({"sessionId": 4})


class TestSessionDetail(unittest.TestCase):
    def test_format_slug_resolves_to_human_title(self):
        self.assertEqual(titles()["the-thing"].showings[0].format, "35mm")

    def test_screen_number_becomes_auditorium(self):
        self.assertEqual(titles()["the-thing"].showings[0].auditorium, "Theater 1")

    def test_sold_out_is_detected(self):
        showings = titles()["spider-man-brand-new-day"].showings
        self.assertFalse(showings[0].sold_out)
        self.assertTrue(showings[1].sold_out)


class TestSeriesTags(unittest.TestCase):
    def test_series_comes_through_as_readable_text(self):
        self.assertIn("Terror Tuesday", titles()["the-thing"].series_tags)

    def test_non_user_visible_attribute_is_skipped(self):
        self.assertNotIn("Internal", titles()["the-thing"].series_tags)

    def test_generic_category_is_carried_not_filtered_here(self):
        # The adapter reports what the feed says; deciding "New Releases" is
        # noise belongs to config/series.toml, not to this module.
        self.assertIn("New Releases", titles()["spider-man-brand-new-day"].series_tags)

    def test_real_admission_policy_is_tagged(self):
        self.assertIn("Rated PG with Adult Focus", titles()["the-thing"].series_tags)

    def test_plain_rating_policy_is_not_tagged(self):
        tags = titles()["spider-man-brand-new-day"].series_tags
        self.assertNotIn("Rated PG-13 (Standard)", tags)


class TestFilmDetail(unittest.TestCase):
    def test_certification_is_carried(self):
        self.assertEqual(titles()["the-thing"].mpa_rating, "R")

    def test_rating_reason_is_none_because_alamo_publishes_none(self):
        # The whole content-signal layer depends on this being honest.
        for t in titles().values():
            self.assertIsNone(t.mpa_reason)

    def test_poster_prefers_poster_images(self):
        self.assertEqual(
            titles()["spider-man-brand-new-day"].poster_source, "https://img/spidey.jpg"
        )

    def test_poster_falls_back_to_hero_image(self):
        self.assertEqual(titles()["the-thing"].poster_source, "https://img/thing.jpg")


class TestFailsLoudly(unittest.TestCase):
    def test_missing_top_level_keys_raise(self):
        with self.assertRaises(DiscoveryPending):
            to_titles({"data": {"market": []}})

    def test_non_object_payload_raises(self):
        with self.assertRaises(DiscoveryPending):
            to_titles({"data": ["nope"]})

    def test_broken_join_raises_rather_than_returning_empty(self):
        broken = {"data": dict(PAYLOAD["data"], sessions=[])}
        with self.assertRaises(DiscoveryPending):
            to_titles(broken)

    def test_session_without_any_timestamp_raises(self):
        bad = {"data": dict(
            PAYLOAD["data"],
            sessions=[{"sessionId": 9, "presentationSlug": "the-thing",
                       "screenNumber": 1, "isHidden": False}],
        )}
        with self.assertRaises(DiscoveryPending):
            to_titles(bad)


if __name__ == "__main__":
    unittest.main(verbosity=2)
