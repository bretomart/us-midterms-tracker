import unittest
import aggregate


class TestAggregate(unittest.TestCase):

    def test_party_group(self):
        self.assertEqual(aggregate.party_group("Democratic"), "D")
        self.assertEqual(aggregate.party_group("Republican"), "R")
        self.assertEqual(aggregate.party_group("Libertarian"), "O")
        self.assertEqual(aggregate.party_group(None), "O")

    def test_normalise_race_no_data(self):
        raw = {
            "id": 1,
            "type": "US Senate",
            "election_name": "Test Senate",
            "province": "CA",
            "district": None,
            "percent_reporting": 0,
            "candidates": [
                {"name": "Alice", "party": "Democratic", "votes": 0, "winner": False},
                {"name": "Bob", "party": "Republican", "votes": 0, "winner": False}
            ]
        }
        n = aggregate.normalise_race(raw)
        self.assertFalse(n["has_data"])
        self.assertEqual(n["total_votes"], 0)
        self.assertIsNone(n["leader"])
        self.assertFalse(n["called"])

    def test_normalise_race_leading(self):
        raw = {
            "id": 2,
            "type": "US Senate",
            "election_name": "Test Senate",
            "province": "CA",
            "district": None,
            "percent_reporting": 10,
            "candidates": [
                {"name": "Alice", "party": "Democratic", "votes": 1000, "winner": False},
                {"name": "Bob", "party": "Republican", "votes": 800, "winner": False}
            ]
        }
        n = aggregate.normalise_race(raw)
        self.assertTrue(n["has_data"])
        self.assertEqual(n["total_votes"], 1800)
        self.assertEqual(n["leader"]["name"], "Alice")
        self.assertEqual(n["leader"]["group"], "D")
        self.assertFalse(n["called"])

    def test_normalise_race_called(self):
        raw = {
            "id": 3,
            "type": "US Senate",
            "election_name": "Test Senate",
            "province": "CA",
            "district": None,
            "percent_reporting": 100,
            "candidates": [
                {"name": "Alice", "party": "Democratic", "votes": 5000, "winner": True},
                {"name": "Bob", "party": "Republican", "votes": 4000, "winner": False}
            ]
        }
        n = aggregate.normalise_race(raw)
        self.assertTrue(n["called"])
        self.assertEqual(n["winner"]["group"], "D")

    def test_tally(self):
        races = [
            {"has_data": True, "called": True, "winner": {"group": "D"}, "multiple_winners": False, "tied": False},
            {"has_data": True, "called": True, "winner": {"group": "R"}, "multiple_winners": False, "tied": False},
            {"has_data": True, "called": False, "tied": False, "leader": {"group": "D"}},
            {"has_data": False, "called": False, "tied": False},
            {"has_data": True, "called": False, "tied": True},
        ]
        res = aggregate.tally(races)
        self.assertEqual(res["races"], 5)
        self.assertEqual(res["no_data"], 1)
        self.assertEqual(res["tied"], 1)
        self.assertEqual(res["called"], {"D": 1, "R": 1, "O": 0})
        self.assertEqual(res["leading"], {"D": 1, "R": 0, "O": 0})

    def test_load_from_fixtures_accuracy(self):
        import server
        payload = server.load_from_fixtures("TEST-FIXTURE")
        self.assertEqual(payload["summary"]["senate"]["contested"], 35)
        self.assertEqual(payload["summary"]["senate"]["tally"]["no_data"], 35)
        self.assertEqual(payload["summary"]["senate"]["tally"]["leading"], {"D": 0, "R": 0, "O": 0})
        self.assertEqual(payload["summary"]["house"]["contested"], 435)
        self.assertEqual(payload["summary"]["house"]["tally"]["no_data"], 435)
        # The feed's three synthetic province="US" rollup rows (Senate, House,
        # Governors) are not contests and must never land on a state board.
        self.assertEqual(payload["summary"]["governor"]["contested"], 39)
        self.assertEqual(payload["summary"]["governor"]["contested_states"], 36)
        self.assertEqual(payload["summary"]["governor"]["territories"], 3)
        self.assertGreater(payload["summary"]["measures"]["contested"], 100)
        self.assertEqual(
            {r["state"] for r in payload["board"]["governor"]} - set("US"),
            {r["state"] for r in payload["board"]["governor"]})
        self.assertNotIn(
            "US", [r["state"] for r in payload["board"]["senate"] + payload["board"]["house"]])

    def test_schedule_and_waves_in_payload(self):
        import server
        payload = server.load_from_fixtures("TEST-FIXTURE")
        self.assertTrue(payload["waves"], "every jurisdiction should land in a wave")
        self.assertEqual(payload["summary"]["senate"]["holdover"],
                         payload["summary"]["senate"]["feed_seats"])
        in_house = next(r for r in payload["board"]["house"] if r["state"] == "IN")
        self.assertEqual(in_house["close_first"], 1080)
        self.assertEqual(in_house["close_last"], 1140)
        self.assertEqual(in_house["close_label"], "7:00 PM ET")
        self.assertTrue(in_house["close_verified"])
        codes = server._jurisdiction_counts(payload["board"])
        sections = payload["board"]
        self.assertEqual(sum(codes.values()),
                         sum(len(sections[k]) for k in ("senate", "house", "governor", "measures")))
        self.assertNotIn("US", codes)
        # Waves account for every race in the feed except unscheduled ones, which
        # appear in the explicit "Unconfirmed" bucket.
        self.assertEqual(sum(w["races_close"] for w in payload["waves"]), sum(codes.values()))

    def test_control_projection(self):
        hold = {"D": 34, "R": 31, "O": 0}
        called = {"D": 17, "R": 3, "O": 0}
        total = {g: hold[g] + called[g] for g in hold}
        ctrl = aggregate.control(total, 51, 20)
        self.assertEqual(ctrl["holder"], "D")
        self.assertEqual(ctrl["state"], "majority")
        self.assertEqual(ctrl["needed"], {"D": 0, "R": 17, "O": 51})
        early = aggregate.control({"D": 40, "R": 40, "O": 0}, 51, 4)
        self.assertEqual(early["state"], "tied")
        self.assertIsNone(early["holder"])
        self.assertFalse(early["decided"])
        quiet = aggregate.control({"D": 0, "R": 0, "O": 0}, 218, 0)
        self.assertEqual(quiet["state"], "undecided")
        self.assertEqual(quiet["needed"]["D"], 218)

    def test_conflicts_detection(self):
        board = {
            "house": [{"has_data": True, "called": True, "winner": {"group": "D"}, "multiple_winners": False, "tied": False, "name": "H1"}],
            "senate": [],
            "governor": [],
            "measures": [],
        }
        national_raw = {
            "house": {"candidates": [{"party": "Democratic", "seats": 3}, {"party": "Republican", "seats": 0}]}
        }
        found = aggregate.conflicts(board, national_raw)
        self.assertEqual(len(found), 1)
        self.assertIn("house D: feed reports 3 seats, called races sum to 1", found[0])
    def test_parse_rss_xml(self):
        import server
        sample_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0">
          <channel>
            <title>Sample Politics</title>
            <item>
              <title><![CDATA[Polls open across key battleground states\xe2\x80\x94early turnout high]]></title>
              <link>https://example.com/polls-open</link>
              <description><![CDATA[<p>Voters head to the polls in <strong>35 Senate contests</strong>.</p>]]></description>
              <pubDate>Tue, 03 Nov 2026 15:30:00 GMT</pubDate>
            </item>
          </channel>
        </rss>"""
        prov = {"id": "msnow", "name": "MS NOW", "color": "#38bdf8"}
        items = server.parse_rss_xml(sample_xml, prov, limit=5)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["provider_id"], "msnow")
        self.assertEqual(items[0]["provider_name"], "MS NOW")
        self.assertNotIn("\u2014", items[0]["title"])
        self.assertIn("Polls open across key battleground states - early turnout high", items[0]["title"])
        self.assertEqual(items[0]["summary"], "Voters head to the polls in 35 Senate contests .")
        self.assertEqual(items[0]["published_at"], "2026-11-03 15:30 UTC")
        self.assertGreater(items[0]["timestamp"], 0)

if __name__ == "__main__":
    unittest.main()
