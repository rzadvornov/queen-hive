"""Acceptance tests written by the product owner. Do not change."""
import unittest

from cache.service import ProfileService
from cache.ttl import TTLCache


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class TTL(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.cache = TTLCache(2, 10, clock=self.clock)

    def test_get_put(self):
        self.cache.put("a", 1)
        self.assertEqual(self.cache.get("a"), 1)
        self.assertEqual(self.cache.get("b", "none"), "none")

    def test_expiry(self):
        self.cache.put("a", 1)
        self.clock.now = 9.9
        self.assertEqual(self.cache.get("a"), 1)
        self.clock.now = 10.0
        self.assertIsNone(self.cache.get("a"))
        self.assertEqual(len(self.cache), 0)

    def test_get_does_not_extend(self):
        self.cache.put("a", 1)
        self.clock.now = 8
        self.cache.get("a")
        self.clock.now = 11
        self.assertIsNone(self.cache.get("a"))

    def test_lru_eviction(self):
        self.cache.put("a", 1)
        self.cache.put("b", 2)
        self.cache.get("a")              # b is now least recently used
        self.cache.put("c", 3)
        self.assertNotIn("b", self.cache)
        self.assertIn("a", self.cache)
        self.assertIn("c", self.cache)

    def test_expired_dropped_before_eviction(self):
        self.cache.put("a", 1)
        self.clock.now = 5
        self.cache.put("b", 2)
        self.clock.now = 12              # a expired, b alive
        self.cache.put("c", 3)
        self.assertIn("b", self.cache)
        self.assertEqual(len(self.cache), 2)

    def test_contains_is_not_a_use(self):
        self.cache.put("a", 1)
        self.cache.put("b", 2)
        "a" in self.cache
        self.cache.put("c", 3)
        self.assertNotIn("a", self.cache)

    def test_replace_and_clear(self):
        self.cache.put("a", 1)
        self.cache.put("a", 2)
        self.assertEqual(self.cache.get("a"), 2)
        self.assertEqual(len(self.cache), 1)
        self.cache.clear()
        self.assertEqual(len(self.cache), 0)

    def test_invalid(self):
        for args in ((0, 1), (1, 0), (1, -1)):
            with self.assertRaises(ValueError):
                TTLCache(*args)

    def test_service_uses_cache(self):
        calls = []
        service = ProfileService(lambda uid: calls.append(uid) or {"id": uid})
        service.profile("u1")
        service.profile("u1")
        self.assertEqual(calls, ["u1"])


if __name__ == "__main__":
    unittest.main()
