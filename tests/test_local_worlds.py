import tempfile
import unittest
from pathlib import Path

from bifrost.local_worlds import install_staged_world, list_worlds


class LocalWorldTests(unittest.TestCase):
    def test_lists_worlds_and_ignores_backups(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            (root / "Asgard").mkdir()
            (root / "Asgard" / "world.db2").write_bytes(b"abc")
            (root / "Asgard_backup_1").mkdir()
            (root / "Asgard_pre_pull_20260101-120000").mkdir()
            worlds = list_worlds(root)
            self.assertEqual([world.name for world in worlds], ["Asgard"])
            self.assertEqual(worlds[0].size_bytes, 3)

    def test_install_keeps_previous_world_as_backup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            current = root / "Asgard"
            current.mkdir()
            (current / "save.db2").write_text("old", encoding="utf-8")
            staged = root / "staged"
            staged.mkdir()
            (staged / "save.db2").write_text("new", encoding="utf-8")

            backup = install_staged_world(root, "Asgard", staged)

            self.assertEqual((root / "Asgard" / "save.db2").read_text(encoding="utf-8"), "new")
            self.assertIsNotNone(backup)
            self.assertEqual((backup / "save.db2").read_text(encoding="utf-8"), "old")  # type: ignore[operator]


if __name__ == "__main__":
    unittest.main()

