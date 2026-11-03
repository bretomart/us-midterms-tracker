import json
import os
import unittest

import aggregate
import ap_source

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def load_sample():
    with open(os.path.join(FIXTURES, "ap_metadata_sample.json"), encoding="utf-8") as fh:
        metadata = json.load(fh)
    with open(os.path.join(FIXTURES, "ap_progress_sample.json"), encoding="utf-8") as fh:
        progress = json.load(fh)
    return metadata, progress


class TestAPSource(unittest.TestCase):

    def setUp(self):
        self.metadata, self.progress = load_sample()
        self.races = ap_source.build_raw_races(self.metadata, self.progress)

    def test_keeps_only_board_offices(self):
        types = {r["type"] for r in self.races}
        self.assertLessEqual(
            types,
            {aggregate.HOUSE_TYPE, aggregate.SENATE_TYPE,
             aggregate.GOVERNOR_TYPE, "Ballot Measure"})
        self.assertIn(aggregate.HOUSE_TYPE, types)
        self.assertIn(aggregate.SENATE_TYPE, types)

    def test_drops_national_rollup(self):
        self.assertFalse([r for r in self.races if r["province"] == "US"])

    def test_house_naming_and_district(self):
        house = [r for r in self.races if r["type"] == aggregate.HOUSE_TYPE]
        self.assertTrue(house)
        for r in house:
            self.assertRegex(r["election_name"], r"^[A-Z][a-z]+ US House \d+$")
            self.assertRegex(r["district"], r"^[A-Z]{2}-\d{2}$")

    def test_parties_expanded_for_grouping(self):
        cands = [c for r in self.races for c in r["candidates"]]
        parties = {c["party"] for c in cands}
        self.assertIn("Republican", parties)
        self.assertIn("Democratic", parties)
        self.assertFalse({"GOP", "Dem"} & parties)

    def test_progress_joined_by_candidate_id(self):
        race = next(r for r in self.races if r["type"] == aggregate.SENATE_TYPE)
        live = self.progress[race["id"]]
        roster = self.metadata[race["id"]]["candidates"]
        self.assertEqual(race["percent_reporting"], live["eevp"])
        self.assertEqual(len(race["candidates"]), len(roster))
        by_id = {c["candidateID"]: c for c in live["candidates"]}
        for cand in race["candidates"]:
            self.assertTrue(cand["name"])
        first = next(c for c in roster.values() if c["candidateID"] in by_id)
        mapped = next(c for c in race["candidates"] if c["name"].endswith(first["last"]))
        self.assertEqual(mapped["votes"], by_id[first["candidateID"]]["voteCount"])

    def test_no_winner_flag_means_not_called(self):
        for r in self.races:
            normalised = aggregate.normalise_race(r)
            self.assertFalse(normalised["called"])

    def test_called_race_carries_winner(self):
        race_id = next(iter(self.metadata))
        meta = dict(self.metadata[race_id])
        meta.update({
            "officeID": "S",
            "statePostal": "KS",
            "raceCallStatus": "Called",
            "candidates": {
                "9": {"candidateID": "9", "first": "Ada", "last": "Reyes",
                      "party": "GOP", "ballotOrder": 1},
                "10": {"candidateID": "10", "first": "Bo", "last": "Lin",
                       "party": "Dem", "ballotOrder": 2},
            },
        })
        progress = {
            race_id: {
                "stateName": "Kansas", "eevp": 87,
                "candidates": [
                    {"candidateID": "9", "voteCount": 610000, "votePct": 54.5, "winner": "X"},
                    {"candidateID": "10", "voteCount": 509000, "votePct": 45.5},
                ],
            },
        }
        raw = ap_source.build_raw_races({race_id: meta}, progress)[0]
        self.assertEqual(raw["call_status"], "Called")
        self.assertEqual(raw["percent_reporting"], 87)
        normalised = aggregate.normalise_race(raw)
        self.assertTrue(normalised["called"])
        self.assertEqual(normalised["winner"]["name"], "Ada Reyes")
        self.assertEqual(normalised["winner"]["group"], "R")
        self.assertEqual(normalised["leader"]["group"], "R")

    def test_source_meta_counts_call_status(self):
        meta = ap_source.source_meta(self.metadata, self.progress)
        self.assertEqual(meta["provider"], "AP")
        self.assertEqual(sum(meta["call_status"].values()), len(self.metadata))
        self.assertTrue(meta["last_updated"])


if __name__ == "__main__":
    unittest.main()
