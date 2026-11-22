import unittest

from cache.service import ProfileService


class Service(unittest.TestCase):
    def test_profile(self):
        service = ProfileService(lambda uid: {"id": uid})
        self.assertEqual(service.profile("u1"), {"id": "u1"})
