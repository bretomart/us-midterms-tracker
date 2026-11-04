import os
import unittest
from unittest import mock

import publish


class FakeClock:
    def __init__(self, start=1000.0):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class TestPublisher(unittest.TestCase):
    def make(self, result=(True, "")):
        clock = FakeClock()
        calls = []

        def runner():
            calls.append(clock.now)
            return result

        log = []
        pub = publish.Publisher(
            cwd="/tmp",
            interval=300,
            backoff=600,
            runner=runner,
            clock=clock,
            log=log.append,
        )
        return pub, clock, calls, log

    def test_dispatches_once_per_interval(self):
        pub, clock, calls, log = self.make()
        self.assertTrue(pub.tick())
        clock.advance(299)
        self.assertFalse(pub.tick())
        self.assertEqual(len(calls), 1)
        clock.advance(1)
        self.assertTrue(pub.tick())
        self.assertEqual(len(calls), 2)
        self.assertEqual(pub.sent, 2)

    def test_failure_backs_off_instead_of_retrying_every_tick(self):
        pub, clock, calls, log = self.make(result=(False, "gh: not logged in"))
        self.assertFalse(pub.tick())
        self.assertEqual(pub.failures, 1)
        clock.advance(300)
        self.assertFalse(pub.tick())
        self.assertEqual(len(calls), 1)
        self.assertIn("gh: not logged in", log[-1])
        clock.advance(300)
        self.assertTrue(clock.now >= pub.next_attempt)
        pub.tick()
        self.assertEqual(len(calls), 2)

    def test_success_resets_backoff_after_a_failure(self):
        runs = [(False, "boom"), (True, "")]

        def runner():
            return runs.pop(0)

        clock = FakeClock()
        pub = publish.Publisher(cwd="/tmp", interval=300, backoff=600,
                                runner=runner, clock=clock, log=lambda m: None)
        pub.tick()
        clock.advance(600)
        pub.tick()
        self.assertEqual(pub.failures, 0)
        clock.advance(299)
        self.assertFalse(pub.due())


class TestFromEnv(unittest.TestCase):
    def test_unset_disables_publishing(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(publish.from_env())

    def test_zero_and_garbage_disable_publishing(self):
        for raw in ("0", "-5", "every five minutes"):
            with mock.patch.dict(os.environ, {"PUBLISH_INTERVAL": raw}):
                self.assertIsNone(publish.from_env(log=lambda m: None), raw)

    def test_positive_value_builds_a_publisher(self):
        with mock.patch.dict(os.environ, {"PUBLISH_INTERVAL": "180"}):
            pub = publish.from_env(cwd="/tmp")
        self.assertIsNotNone(pub)
        self.assertEqual(pub.interval, 180)


if __name__ == "__main__":
    unittest.main()
