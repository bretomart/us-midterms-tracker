import unittest

import aggregate
import nbc_source


class TestNBCSource(unittest.TestCase):

    def setUp(self):
        self.sample = {
            "lastUpdated": "2026-11-04T02:15:00Z",
            "races": [
                {
                    "id": "nbc-house-va-07",
                    "office": "house",
                    "state": "VA",
                    "district": "07",
                    "status": "Called",
                    "reporting": 98.4,
                    "candidates": [
                        {
                            "name": "Eugene Vindman",
                            "party": "DEM",
                            "votes": 195230,
                            "percent": 51.2,
                            "winner": True,
                        },
                        {
                            "name": "Derrick Anderson",
                            "party": "GOP",
                            "votes": 186100,
                            "percent": 48.8,
                            "winner": False,
                        },
                    ],
                },
                {
                    "id": "nbc-senate-oh",
                    "office": "senate",
                    "state": "OH",
                    "status": "Called",
                    "reporting": 99.1,
                    "candidates": [
                        {
                            "name": "Sherrod Brown",
                            "party": "DEM",
                            "votes": 2510000,
                            "percent": 49.8,
                            "winner": False,
                        },
                        {
                            "name": "Bernie Moreno",
                            "party": "GOP",
                            "votes": 2530000,
                            "percent": 50.2,
                            "winner": True,
                        },
                    ],
                },
                {
                    "id": "nbc-gov-nc",
                    "office": "governor",
                    "state": "NC",
                    "status": "Called",
                    "reporting": 95.0,
                    "candidates": [
                        {
                            "name": "Josh Stein",
                            "party": "DEM",
                            "votes": 2900000,
                            "percent": 54.8,
                            "winner": True,
                        },
                        {
                            "name": "Mark Robinson",
                            "party": "GOP",
                            "votes": 2100000,
                            "percent": 40.1,
                            "winner": False,
                        },
                    ],
                },
            ],
        }

    def test_build_raw_races(self):
        races = nbc_source.build_raw_races(self.sample)
        self.assertEqual(len(races), 3)

        house = next(r for r in races if r["type"] == aggregate.HOUSE_TYPE)
        self.assertEqual(house["province"], "VA")
        self.assertEqual(house["district"], "VA-07")
        self.assertEqual(house["call_status"], "Called")
        self.assertEqual(house["candidates"][0]["name"], "Eugene Vindman")
        self.assertEqual(house["candidates"][0]["party"], "Democratic")
        self.assertTrue(house["candidates"][0]["winner"])

        norm = aggregate.normalise_race(house)
        self.assertTrue(norm["called"])
        self.assertEqual(norm["winner"]["name"], "Eugene Vindman")
        self.assertEqual(norm["winner"]["group"], "D")

    def test_senate_race_normalization(self):
        races = nbc_source.build_raw_races(self.sample)
        senate = next(r for r in races if r["type"] == aggregate.SENATE_TYPE)
        norm = aggregate.normalise_race(senate)
        self.assertTrue(norm["called"])
        self.assertEqual(norm["winner"]["name"], "Bernie Moreno")
        self.assertEqual(norm["winner"]["group"], "R")


if __name__ == "__main__":
    unittest.main()
