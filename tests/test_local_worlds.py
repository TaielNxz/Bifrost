import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from bifrost.local_worlds import COPIES_DIRECTORY_NAME, find_world, install_staged_world, list_worlds
from bifrost.world_names import InvalidWorldNameError, WorldNameConflictError


class LocalWorldTests(unittest.TestCase):
    def test_lists_worlds_and_ignores_backups(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            (root / "Asgard").mkdir()
            (root / "Asgard" / "world.db2").write_bytes(b"abc")
            (root / "Asgard_backup_1").mkdir()
            (root / "Asgard_pre_pull_20260101-120000").mkdir()
            (root / COPIES_DIRECTORY_NAME).mkdir()
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

    def test_lists_valid_names_with_spaces_and_accents_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            for name in ("Peña del Dragón", "Bifröst"):
                (root / name).mkdir()
                (root / name / "save.db").write_bytes(b"world")
            errors = []
            worlds = list_worlds(root, errors=errors)
            self.assertEqual([world.name for world in worlds], ["Bifröst", "Peña del Dragón"])
            self.assertEqual([world.size_bytes for world in worlds], [5, 5])
            self.assertEqual(errors, [])

    def test_rejected_directories_are_not_traversed_or_sized(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            valid = root / "Bifröst"
            valid.mkdir()
            rejected = []
            # Simula nombres que Windows no permite crear y carpetas distintas por mayúsculas.
            for name in ("Asgard", "asgard", "NUL", "Mundo."):
                entry = Mock(spec=Path)
                entry.name = name
                entry.is_dir.return_value = True
                rejected.append(entry)
            errors = []
            with (
                patch.object(Path, "iterdir", return_value=iter([valid, *rejected])),
                patch("bifrost.local_worlds.directory_size", return_value=0) as size,
            ):
                worlds = list_worlds(root, errors=errors)
            self.assertEqual([world.name for world in worlds], ["Bifröst"])
            size.assert_called_once_with(valid)
            for entry in rejected:
                entry.stat.assert_not_called()
            self.assertEqual(len(errors), 3)
            self.assertIsInstance(errors[-1], WorldNameConflictError)

    def test_ignores_internal_directories_regardless_of_case(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            for name in ("Asgard", "Asgard_BACKUP_1", "Asgard_PRE_PULL_1", ".BIFROST-COPIES"):
                (root / name).mkdir()
            errors = []
            self.assertEqual([world.name for world in list_worlds(root, errors=errors)], ["Asgard"])
            self.assertEqual(errors, [])

    def test_find_world_preserves_actual_name_and_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            (root / "Peña del Dragón").mkdir()
            world = find_world(root, "PEÑA DEL DRAGÓN")
            self.assertIsNotNone(world)
            self.assertEqual(world.name, "Peña del Dragón")
            self.assertEqual(world.path, root / "Peña del Dragón")
            self.assertIsNone(find_world(root, "Otro mundo"))

    def test_find_world_does_not_treat_case_conflict_as_an_absent_world(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            entries = []
            for name in ("Asgard", "asgard"):
                entry = Mock(spec=Path)
                entry.name = name
                entry.is_dir.return_value = True
                entries.append(entry)
            with patch.object(Path, "iterdir", return_value=iter(entries)):
                with self.assertRaises(WorldNameConflictError) as caught:
                    find_world(temporary_dir, "ASGARD")
            self.assertEqual(caught.exception.names, ("Asgard", "asgard"))

    def test_find_world_rejects_invalid_name_before_listing(self) -> None:
        with patch("bifrost.local_worlds.list_worlds") as listing:
            with self.assertRaises(InvalidWorldNameError):
                find_world("unused", "../Asgard")
        listing.assert_not_called()


if __name__ == "__main__":
    unittest.main()

