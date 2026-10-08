import unittest
from datetime import datetime, timedelta, timezone

from bifrost.locks import build_lock, ensure_restore_unlocked, is_expired


class LockTests(unittest.TestCase):
    def test_lock_expiration(self) -> None:
        acquired = datetime(2026, 1, 1, tzinfo=timezone.utc)
        world_lock = build_lock("Taiel", machine="PC", now=acquired, duration_hours=12)
        self.assertFalse(is_expired(world_lock, acquired + timedelta(hours=11)))
        self.assertTrue(is_expired(world_lock, acquired + timedelta(hours=13)))
        self.assertEqual(world_lock["player"], "Taiel")
        self.assertEqual(world_lock["machine"], "PC")



class RestoreLockTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 1, 2, tzinfo=timezone.utc)
        self.expired = build_lock("Taiel", machine="PC", now=self.now - timedelta(days=1))

    def test_absent_and_valid_expired_legacy_locks_allow_restoration(self) -> None:
        ensure_restore_unlocked(None, self.now)
        ensure_restore_unlocked(self.expired, self.now)
        legacy = {key: value for key, value in self.expired.items() if key != "session_id"}
        ensure_restore_unlocked(legacy, self.now)

    def test_active_lock_and_exact_expiration_block_regardless_of_owner(self) -> None:
        for player in ("Taiel", "Otro"):
            with self.subTest(player=player):
                lock = build_lock(player, machine="PC", now=self.now - timedelta(hours=12))
                with self.assertRaisesRegex(RuntimeError, "activo"):
                    ensure_restore_unlocked(lock, self.now)

    def test_invalid_expired_data_also_blocks_restoration(self) -> None:
        invalid_values = (
            [], {}, {**self.expired, "player": ""}, {**self.expired, "machine": None},
            {**self.expired, "acquired_at": "mal"}, {**self.expired, "expires_at": 123},
            {**self.expired, "expires_at": "2026-01-01T12:00:00"},
            {**self.expired, "expires_at": "2026-01-01T12:00:00+03:00"},
            {**self.expired, "expires_at": "2025-01-01T00:00:00Z"},
            {**self.expired, "session_id": None}, {**self.expired, "session_id": " "},
            {**self.expired, "base_version": None}, {**self.expired, "base_version": True},
            {**self.expired, "base_version": 0},
        )
        for lock in invalid_values:
            with self.subTest(lock=lock):
                with self.assertRaisesRegex(RuntimeError, "no es válido"):
                    ensure_restore_unlocked(lock, self.now)
if __name__ == "__main__":
    unittest.main()

