import unittest
from datetime import datetime, timedelta, timezone

from bifrost.locks import build_lock, is_expired


class LockTests(unittest.TestCase):
    def test_lock_expiration(self) -> None:
        acquired = datetime(2026, 1, 1, tzinfo=timezone.utc)
        world_lock = build_lock("Taiel", machine="PC", now=acquired, duration_hours=12)
        self.assertFalse(is_expired(world_lock, acquired + timedelta(hours=11)))
        self.assertTrue(is_expired(world_lock, acquired + timedelta(hours=13)))
        self.assertEqual(world_lock["player"], "Taiel")
        self.assertEqual(world_lock["machine"], "PC")


if __name__ == "__main__":
    unittest.main()

