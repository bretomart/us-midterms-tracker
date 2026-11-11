import json
import os
import shutil
import tempfile
import unittest

import aggregate
import call_log

HOUSE = "house|FL|FL-%02d"


def race(race_id, called=True, reporting=0, total_votes=0, state="FL", district=None,
         race_type=aggregate.HOUSE_TYPE):
    """One board row. House districts follow the id so each race is distinct."""
    if race_type == aggregate.HOUSE_TYPE and district is None:
        district = f"{state}-{int(race_id):02d}"
    return {
        "id": race_id,
        "called": called,
        "reporting": reporting,
        "total_votes": total_votes,
        "name": f"Race {race_id}",
        "state": state,
        "district": district,
        "type": race_type,
        "winner": {"name": "Candidate A", "party": "Republican", "group": "R"},
    }


def empty_board(**sections):
    board = {"senate": [], "house": [], "governor": [], "measures": []}
    board.update(sections)
    return board


class IsolatedLedger:
    """Keep observe() off the committed seed and the developer's state log."""

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


class TestCallLog(IsolatedLedger, unittest.TestCase):

    def write_seed(self, started_epoch, calls):
        with open(call_log.SEED_PATH, "w", encoding="utf-8") as fh:
            json.dump({"started_epoch": started_epoch, "calls": calls}, fh)

    def test_calls_seen_during_settling_are_unorderable(self):
        log = call_log.observe([race(1, reporting=90), race(2, reporting=10)], epoch=1000.0)
        self.assertEqual(log["calls"], {HOUSE % 1: 0.0, HOUSE % 2: 0.0})
        self.assertEqual(log["started_epoch"], 1000.0)

    def test_unstamped_section_picks_the_furthest_along_race(self):
        log = call_log.observe([race(1, reporting=12), race(2, reporting=81)], epoch=1000.0)
        picked = call_log.last_by_section(empty_board(house=[race(1, reporting=12),
                                                             race(2, reporting=81)]), log)
        self.assertFalse(picked["house"]["known"])
        self.assertIsNone(picked["house"]["epoch"])
        self.assertEqual(picked["house"]["id"], 2)
        self.assertEqual(picked["house"]["winner"]["group"], "R")

    def test_call_after_settling_is_stamped_and_becomes_last(self):
        call_log.observe([race(1), race(2)], epoch=1000.0)
        log = call_log.observe([race(1), race(2), race(3)], epoch=1000.0 + call_log.SETTLE_SECONDS + 5)
        self.assertEqual(log["calls"][HOUSE % 3], 1000.0 + call_log.SETTLE_SECONDS + 5)
        picked = call_log.last_by_section(empty_board(house=[race(1), race(2), race(3)]), log)
        self.assertTrue(picked["house"]["known"])
        self.assertEqual(picked["house"]["id"], 3)

    def test_cold_start_seeds_the_committed_history(self):
        self.write_seed(1000.0, {HOUSE % 7: 1200.0})
        self.assertTrue(call_log.seed_from_fixture())
        log = call_log.observe([race(7), race(8)], epoch=9000.0)
        # The seeded stamp survives and a call the seed never saw is stamped
        # now: a seeded ledger is past its settle window.
        self.assertEqual(log["calls"][HOUSE % 7], 1200.0)
        self.assertEqual(log["calls"][HOUSE % 8], 9000.0)
        self.assertEqual(log["started_epoch"], 1000.0)

    def test_seed_merges_without_losing_live_stamps(self):
        # A ledger past its settle window orders calls of its own. Merging the
        # seed may add history it lacks but must never lower a stamp.
        call_log.observe([race(1)], epoch=1000.0)
        call_log.observe([race(1), race(2)], epoch=1000.0 + call_log.SETTLE_SECONDS + 5)
        self.write_seed(1000.0, {HOUSE % 7: 1200.0})
        self.assertTrue(call_log.seed_from_fixture())
        state = call_log._read()
        self.assertEqual(state["calls"][HOUSE % 7], 1200.0)
        self.assertEqual(state["calls"][HOUSE % 2],
                         1000.0 + call_log.SETTLE_SECONDS + 5)

    def test_seed_merge_is_idempotent(self):
        self.write_seed(1000.0, {HOUSE % 7: 1200.0})
        self.assertTrue(call_log.seed_from_fixture())
        self.assertFalse(call_log.seed_from_fixture())
        self.assertEqual(call_log._read()["calls"], {HOUSE % 7: 1200.0})

    def test_a_legacy_ledger_gains_the_seed_history(self):
        # Re-keying the ledger strands an existing cache: its stamps sit under
        # feed ids no live row produces. The merge still has to run, or that
        # build reports every ordered call as made before tracking began.
        call_log._write({"started_epoch": 1000.0, "calls": {"1": 1100.0, "2": 1200.0}})
        call_log._CACHE = None
        self.write_seed(900.0, {HOUSE % 7: 1500.0})
        self.assertTrue(call_log.seed_from_fixture())
        log = call_log.observe([race(7)], epoch=9000.0)
        self.assertEqual(log["calls"][HOUSE % 7], 1500.0)
        self.assertEqual(log["started_epoch"], 900.0)

    def test_ledger_without_stamps_takes_the_seed_history(self):
        call_log.observe([race(7), race(8)], epoch=1000.0)
        self.write_seed(900.0, {HOUSE % 7: 1200.0, HOUSE % 9: 1500.0})
        self.assertTrue(call_log.seed_from_fixture())
        log = call_log._read()
        self.assertEqual(log["started_epoch"], 900.0)
        self.assertEqual(log["calls"][HOUSE % 7], 1200.0)
        self.assertEqual(log["calls"][HOUSE % 9], 1500.0)
        # The race only this ledger saw stays unordered rather than borrowing a time.
        self.assertEqual(log["calls"][HOUSE % 8], 0.0)

    def test_missing_seed_leaves_the_ledger_empty(self):
        self.assertFalse(call_log.seed_from_fixture())
        self.assertFalse(os.path.exists(call_log.LOG_PATH))

    def test_latest_stamp_wins_over_higher_reporting(self):
        call_log.observe([race(1)], epoch=1000.0)
        call_log.observe([race(2)], epoch=2000.0)
        call_log.observe([race(3)], epoch=3000.0)
        log = call_log.observe([], epoch=3001.0)
        board = empty_board(house=[race(1, reporting=99), race(2, reporting=50),
                                   race(3, reporting=2)])
        self.assertEqual(call_log.last_by_section(board, log)["house"]["id"], 3)

    def test_log_survives_a_restart(self):
        call_log.observe([race(1)], epoch=1000.0)
        call_log.observe([race(2)], epoch=5000.0)
        call_log._CACHE = None
        log = call_log.observe([race(1), race(2)], epoch=9000.0)
        self.assertEqual(log["calls"], {HOUSE % 1: 0.0, HOUSE % 2: 5000.0})
        self.assertEqual(log["started_epoch"], 1000.0)

    def test_uncalled_races_are_never_stamped(self):
        log = call_log.observe([race(1, called=False), race(2, called=True)], epoch=1000.0)
        self.assertNotIn(HOUSE % 1, log["calls"])

    def test_section_without_calls_reports_none(self):
        log = call_log.observe([race(1)], epoch=1000.0)
        picked = call_log.last_by_section(empty_board(house=[race(1)]), log)
        self.assertIsNone(picked["senate"])
        self.assertIsNone(picked["measures"])
        self.assertEqual(picked["house"]["id"], 1)


class TestRaceIdentity(IsolatedLedger, unittest.TestCase):

    def test_senate_and_governor_ignore_the_district_label(self):
        # AP puts the class in district, civicAPI leaves it empty or repeats the
        # state; neither may change the identity.
        ap = {"id": "20261103AK3079", "type": aggregate.SENATE_TYPE,
              "state": "AK", "district": "Class II"}
        civic = {"id": 86916, "type": aggregate.SENATE_TYPE, "state": "AK", "district": None}
        self.assertEqual(call_log.race_identity(ap), call_log.race_identity(civic))
        self.assertEqual(call_log.race_identity(civic), "senate|AK")

        ap_gov = {"id": "20261103AK2010", "type": aggregate.GOVERNOR_TYPE,
                  "state": "AK", "district": None}
        civic_gov = {"id": 148898, "type": aggregate.GOVERNOR_TYPE,
                     "state": "AK", "district": "AK"}
        self.assertEqual(call_log.race_identity(ap_gov), call_log.race_identity(civic_gov))
        self.assertEqual(call_log.race_identity(civic_gov), "governor|AK")

    def test_house_at_large_labels_fold_onto_district_one(self):
        ap = {"id": "20261103DE00001", "type": aggregate.HOUSE_TYPE,
              "state": "DE", "district": "DE-01"}
        civic = {"id": 87035, "type": aggregate.HOUSE_TYPE,
                 "state": "DE", "district": "DE-AL"}
        self.assertEqual(call_log.race_identity(ap), call_log.race_identity(civic))
        self.assertEqual(call_log.race_identity(civic), "house|DE|DE-01")

    def test_districted_house_races_keep_their_district(self):
        self.assertEqual(call_log.race_identity(
            {"type": aggregate.HOUSE_TYPE, "state": "CA", "district": "CA-07"}),
            "house|CA|CA-07")

    def test_measures_have_no_cross_feed_identity(self):
        # AP "Alabama 4: Require citizenship to vote" and civicAPI "Alabama
        # Amendment 4" name the same measure differently and the numbers
        # collide, so measures stay keyed by feed id.
        row = {"id": "20261103AK85116", "type": "Ballot Measure",
               "state": "AK", "district": "3"}
        self.assertIsNone(call_log.race_identity(row))
        self.assertEqual(call_log._key(row), "20261103AK85116")

    def test_a_feed_switch_keeps_the_stamp(self):
        # The regression this guards: an AP-era stamp and a civic-era stamp for
        # one race used to be two ledger entries, so a build that switched
        # sources lost the call time and the card named the snapshot's older
        # race "last called" while the seat count moved on.
        fl02 = {"id": "20261103FL02", "called": True, "reporting": 40,
                "total_votes": 100, "name": "Florida US House 2", "state": "FL",
                "district": "FL-02", "type": aggregate.HOUSE_TYPE,
                "winner": {"name": "A", "party": "Republican", "group": "R"}}
        call_log.observe([race(1)], epoch=1000.0)
        log = call_log.observe([race(1), fl02], epoch=1000.0 + call_log.SETTLE_SECONDS + 5)
        self.assertEqual(log["calls"][HOUSE % 2], 1000.0 + call_log.SETTLE_SECONDS + 5)

        civic = [dict(race(1), id=901), dict(fl02, id=902)]
        log = call_log.observe(civic, epoch=1000.0 + 2 * call_log.SETTLE_SECONDS + 10)
        self.assertEqual(len(log["calls"]), 2)
        self.assertEqual(log["calls"][HOUSE % 2], 1000.0 + call_log.SETTLE_SECONDS + 5)

        picked = call_log.last_by_section(empty_board(house=civic), log)
        self.assertTrue(picked["house"]["known"])
        self.assertEqual(picked["house"]["id"], 902)

    def test_a_legacy_id_stamp_is_carried_to_the_identity(self):
        # The Actions cache holds stamps written under feed ids. Re-keying must
        # not discard a real observed time: the first poll that reads the row
        # moves the stamp onto its identity.
        call_log._write({"started_epoch": 1000.0,
                         "calls": {"20261103FL02": 1500.0}})
        call_log._CACHE = None
        row = {"id": "20261103FL02", "called": True, "reporting": 40,
               "name": "Florida US House 2", "state": "FL", "district": "FL-02",
               "type": aggregate.HOUSE_TYPE,
               "winner": {"name": "A", "party": "Republican", "group": "R"}}
        log = call_log.observe([row], epoch=1000.0 + 2 * call_log.SETTLE_SECONDS)
        self.assertEqual(log["calls"], {HOUSE % 2: 1500.0})
        self.assertEqual(call_log._read()["calls"], {HOUSE % 2: 1500.0})


class TestCommittedSeed(unittest.TestCase):
    """The published ledger must survive the feeds it is read against."""

    @classmethod
    def setUpClass(cls):
        base = os.path.dirname(os.path.abspath(__file__))
        rows = []
        for name in ("general_2026-11-03.json", "statewide_2026-11-03.json"):
            with open(os.path.join(base, "fixtures", name), encoding="utf-8") as fh:
                rows += json.load(fh)["races"]
        cls.civic_board = aggregate.split_board([aggregate.normalise_race(r) for r in rows])

    def civic_keys(self):
        return {call_log._key(r) for name in call_log.SECTIONS
                for r in self.civic_board[name] if call_log._key(r) is not None}

    def test_seed_keys_are_derivable_from_the_civic_feed(self):
        # Every ordered stamp in the committed seed must be reachable by the
        # identity rule applied to civicAPI rows, or a build on the fallback
        # source loses that call time. Measures are exempt: they keep feed ids.
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "fixtures", "call_log.json"), encoding="utf-8") as fh:
            calls = json.load(fh)["calls"]
        keys = self.civic_keys()
        unmatched = sorted(k for k in calls if k not in keys and "|" in k)
        self.assertEqual(unmatched, [])

    def test_seed_holds_no_feed_ids_for_ordered_sections(self):
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "fixtures", "call_log.json"), encoding="utf-8") as fh:
            calls = json.load(fh)["calls"]
        # Only measure keys (AP ids, no "|" separator) may be id-keyed.
        id_keyed = [k for k in calls if "|" not in k]
        self.assertTrue(id_keyed)
        self.assertTrue(all(k.startswith("2026") for k in id_keyed))

    def test_identity_is_unique_within_a_section(self):
        # A collision would silently merge two races' stamps. Two senate
        # contests in one state, or a feed emitting both DE-01 and DE-AL,
        # would land here.
        keys = self.civic_keys()
        seen = {}
        for name in call_log.SECTIONS:
            for row in self.civic_board[name]:
                key = call_log._key(row)
                if key is None:
                    continue
                self.assertNotIn(key, seen, f"{key} claimed by {seen.get(key)} and {row['id']}")
                seen[key] = row["id"]


if __name__ == "__main__":
    unittest.main()
