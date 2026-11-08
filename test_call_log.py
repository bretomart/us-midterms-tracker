import json
import os
import shutil
import tempfile
import unittest

import call_log


def race(race_id, called=True, reporting=0, total_votes=0):
    return {
        "id": race_id,
        "called": called,
        "reporting": reporting,
        "total_votes": total_votes,
        "name": f"Race {race_id}",
        "state": "FL",
        "district": None,
        "type": "U.S. Senate",
        "winner": {"name": "Candidate A", "party": "Republican", "group": "R"},
    }


def empty_board(**sections):
    board = {"senate": [], "house": [], "governor": [], "measures": []}
    board.update(sections)
    return board


class TestCallLog(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self._state_dir = call_log.STATE_DIR
        self._log_path = call_log.LOG_PATH
        self._seed_path = call_log.SEED_PATH
        call_log.STATE_DIR = self.dir
        call_log.LOG_PATH = os.path.join(self.dir, "call_log.json")
        call_log.SEED_PATH = os.path.join(self.dir, "seed.json")
        call_log._CACHE = None

    def tearDown(self):
        call_log.STATE_DIR = self._state_dir
        call_log.LOG_PATH = self._log_path
        call_log.SEED_PATH = self._seed_path
        call_log._CACHE = None
        shutil.rmtree(self.dir, ignore_errors=True)

    def write_seed(self, started_epoch, calls):
        with open(call_log.SEED_PATH, "w", encoding="utf-8") as fh:
            json.dump({"started_epoch": started_epoch, "calls": calls}, fh)

    def test_calls_seen_during_settling_are_unorderable(self):
        log = call_log.observe([race(1, reporting=90), race(2, reporting=10)], epoch=1000.0)
        self.assertEqual(log["calls"], {"1": 0.0, "2": 0.0})
        self.assertEqual(log["started_epoch"], 1000.0)

    def test_unstamped_section_picks_the_furthest_along_race(self):
        log = call_log.observe([race(1, reporting=12), race(2, reporting=81)], epoch=1000.0)
        picked = call_log.last_by_section(empty_board(senate=[race(1, reporting=12),
                                                            race(2, reporting=81)]), log)
        self.assertFalse(picked["senate"]["known"])
        self.assertIsNone(picked["senate"]["epoch"])
        self.assertEqual(picked["senate"]["id"], 2)
        self.assertEqual(picked["senate"]["winner"]["group"], "R")

    def test_call_after_settling_is_stamped_and_becomes_last(self):
        call_log.observe([race(1), race(2)], epoch=1000.0)
        log = call_log.observe([race(1), race(2), race(3)], epoch=1000.0 + call_log.SETTLE_SECONDS + 5)
        self.assertEqual(log["calls"]["3"], 1000.0 + call_log.SETTLE_SECONDS + 5)
        picked = call_log.last_by_section(empty_board(senate=[race(1), race(2), race(3)]), log)
        self.assertTrue(picked["senate"]["known"])
        self.assertEqual(picked["senate"]["id"], 3)

    def test_cold_start_seeds_the_committed_history(self):
        self.write_seed(1000.0, {"7": 1200.0})
        self.assertTrue(call_log.seed_from_fixture())
        log = call_log.observe([race(7), race(8)], epoch=9000.0)
        # The seeded stamp survives and a call the seed never saw is stamped
        # now: a seeded ledger is past its settle window.
        self.assertEqual(log["calls"]["7"], 1200.0)
        self.assertEqual(log["calls"]["8"], 9000.0)
        self.assertEqual(log["started_epoch"], 1000.0)

    def test_seed_does_not_overwrite_a_live_ledger(self):
        # A ledger past its settle window already orders calls of its own.
        call_log.observe([race(1)], epoch=1000.0)
        call_log.observe([race(1), race(2)], epoch=1000.0 + call_log.SETTLE_SECONDS + 5)
        self.write_seed(1000.0, {"7": 1200.0})
        self.assertFalse(call_log.seed_from_fixture())
        self.assertNotIn("7", call_log._read()["calls"])
        self.assertEqual(call_log._read()["calls"]["2"], 1000.0 + call_log.SETTLE_SECONDS + 5)

    def test_ledger_without_stamps_takes_the_seed_history(self):
        call_log.observe([race(7), race(8)], epoch=1000.0)
        self.write_seed(900.0, {"7": 1200.0, "9": 1500.0})
        self.assertTrue(call_log.seed_from_fixture())
        log = call_log._read()
        self.assertEqual(log["started_epoch"], 900.0)
        self.assertEqual(log["calls"]["7"], 1200.0)
        self.assertEqual(log["calls"]["9"], 1500.0)
        # The id only this ledger saw stays unordered rather than borrowing a time.
        self.assertEqual(log["calls"]["8"], 0.0)

    def test_missing_seed_leaves_the_ledger_empty(self):
        self.assertFalse(call_log.seed_from_fixture())
        self.assertFalse(os.path.exists(call_log.LOG_PATH))

    def test_latest_stamp_wins_over_higher_reporting(self):
        call_log.observe([race(1)], epoch=1000.0)
        call_log.observe([race(2)], epoch=2000.0)
        call_log.observe([race(3)], epoch=3000.0)
        log = call_log.observe([], epoch=3001.0)
        board = empty_board(senate=[race(1, reporting=99), race(2, reporting=50), race(3, reporting=2)])
        self.assertEqual(call_log.last_by_section(board, log)["senate"]["id"], 3)

    def test_log_survives_a_restart(self):
        call_log.observe([race(1)], epoch=1000.0)
        call_log.observe([race(2)], epoch=5000.0)
        call_log._CACHE = None
        log = call_log.observe([race(1), race(2)], epoch=9000.0)
        self.assertEqual(log["calls"], {"1": 0.0, "2": 5000.0})
        self.assertEqual(log["started_epoch"], 1000.0)

    def test_uncalled_races_are_never_stamped(self):
        log = call_log.observe([race(1, called=False), race(2, called=True)], epoch=1000.0)
        self.assertNotIn("1", log["calls"])

    def test_section_without_calls_reports_none(self):
        log = call_log.observe([race(1)], epoch=1000.0)
        picked = call_log.last_by_section(empty_board(senate=[race(1)]), log)
        self.assertIsNone(picked["house"])
        self.assertIsNone(picked["measures"])
        self.assertEqual(picked["senate"]["id"], 1)


if __name__ == "__main__":
    unittest.main()
