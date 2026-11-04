import copy
import json
import os
import unittest

import exitpoll

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def load_raw_sample():
    with open(os.path.join(FIXTURES, "exitpolls_raw_sample.json"), encoding="utf-8") as fh:
        return json.load(fh)


class TestExitPollNormalize(unittest.TestCase):

    def setUp(self):
        self.raw = load_raw_sample()

    def test_candidates_collapse_to_two_parties(self):
        payload = exitpoll.normalize(self.raw)
        self.assertEqual(
            [(c["party"], c["label"]) for c in payload["candidates"]],
            [("dem", "Democrat"), ("rep", "Republican")])

    def test_answer_carries_share_and_both_parties(self):
        payload = exitpoll.normalize(self.raw)
        male = payload["subsets"][0]["questions"][0]["answers"][0]
        self.assertEqual(male["label"], "Male")
        self.assertEqual(male["share"], 47)
        self.assertEqual((male["dem"], male["rep"]), (48, 49))

    def test_repeated_titles_get_variant_numbers(self):
        raw = copy.deepcopy(self.raw)
        polls = raw["nationalExitPollData"][0]["polls"]
        source = polls["polls"][0]
        polls["polls"] = [source, copy.deepcopy(source), copy.deepcopy(source)]
        payload = exitpoll.normalize(raw)
        questions = payload["subsets"][0]["questions"]
        self.assertEqual([q["question"] for q in questions], ["Gender"] * 3)
        self.assertEqual([q["variant"] for q in questions], [1, 2, 3])

    def test_missing_values_stay_null(self):
        raw = copy.deepcopy(self.raw)
        raw["nationalExitPollData"][0]["polls"]["polls"][0]["answers"][0]["values"] = []
        payload = exitpoll.normalize(raw)
        first = payload["subsets"][0]["questions"][0]["answers"][0]
        self.assertIsNone(first["dem"])
        self.assertIsNone(first["rep"])
        self.assertEqual(first["share"], 47)

    def test_out_of_order_values_match_by_colour(self):
        raw = copy.deepcopy(self.raw)
        answer = raw["nationalExitPollData"][0]["polls"]["polls"][0]["answers"][0]
        answer["values"] = list(reversed(answer["values"]))
        payload = exitpoll.normalize(raw)
        row = payload["subsets"][0]["questions"][0]["answers"][0]
        self.assertEqual((row["dem"], row["rep"]), (48, 49))

    def test_unclosed_polls_are_not_ready(self):
        raw = copy.deepcopy(self.raw)
        for group in raw["nationalExitPollData"]:
            group["polls"]["showPollsNotClosedText"] = True
        payload = exitpoll.normalize(raw)
        self.assertFalse(payload["ready"])
        self.assertEqual(payload["note"], "Come back after 8:00pm ET for complete national exit poll results.")

    def test_credit_and_methodology_are_plain_text(self):
        payload = exitpoll.normalize(self.raw)
        self.assertEqual(payload["credit"], "SSRS")
        self.assertIn("exit polling across the country", payload["methodology"])
        self.assertNotIn("**", payload["methodology"])

    def test_empty_document_is_reported_not_invented(self):
        payload = exitpoll.normalize({})
        self.assertFalse(payload["ready"])
        self.assertEqual(payload["subsets"], [])
        self.assertTrue(payload["note"])


class TestExitPollFixture(unittest.TestCase):
    """The shipped warm-up fixture must match what the page expects."""

    def setUp(self):
        with open(os.path.join(FIXTURES, "exitpolls_2026-11-03.json"), encoding="utf-8") as fh:
            self.payload = json.load(fh)

    def test_every_group_keeps_all_questions(self):
        titles = [s["title"] for s in self.payload["subsets"]]
        self.assertEqual(len(titles), 13)
        self.assertEqual(titles[0], "All Voters")
        for subset in self.payload["subsets"]:
            self.assertEqual(len(subset["questions"]), 136)
            self.assertTrue(all(q["answers"] for q in subset["questions"]))


if __name__ == "__main__":
    unittest.main()
