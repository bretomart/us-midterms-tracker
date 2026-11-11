import unittest

import server


class DedupeRacesTests(unittest.TestCase):
    def test_last_race_wins_per_id_and_order_is_first_seen(self):
        a1 = {"id": 1, "v": "old"}
        b = {"id": 2}
        a2 = {"id": 1, "v": "new"}
        self.assertEqual(server._dedupe_races([a1, b, a2]), [a2, b])

    def test_races_without_an_id_are_dropped(self):
        self.assertEqual(server._dedupe_races([{"name": "x"}, {"id": None}]), [])

    def test_none_is_an_empty_feed(self):
        self.assertEqual(server._dedupe_races(None), [])

    def test_malformed_entries_are_skipped_not_fatal(self):
        good = {"id": 7}
        self.assertEqual(server._dedupe_races([None, "x", 3, good]), [good])


if __name__ == "__main__":
    unittest.main()
