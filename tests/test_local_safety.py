import json
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from bifrost.archives import create_zip
from bifrost.local_paths import ensure_local_path
from bifrost.local_state import STATE_FILENAME, read_base_version, save_base_version
from bifrost.local_worlds import (
    COPIES_DIRECTORY_NAME, backup_world, find_world, install_staged_world,
    list_worlds, save_world_copy,
)
from bifrost.world_names import InvalidWorldNameError, WorldNameConflictError


def make_directory_link(link: Path, target: Path) -> None:
    """Crea un enlace temporal; usa una junction si Windows no permite enlaces simbólicos."""
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError as error:
        if os.name != "nt" or getattr(error, "winerror", None) != 1314:
            raise
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            check=True, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW,
        )


class LocalSafetyTests(unittest.TestCase):
    def test_paths_outside_the_root_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir) / "worlds"
            root.mkdir()
            for path in (root / ".." / "outside", root.parent / "outside", root):
                with self.subTest(path=path), self.assertRaises(RuntimeError):
                    ensure_local_path(root, path)
            self.assertEqual(ensure_local_path(root, root / "Peña del Dragón"), root / "Peña del Dragón")
            self.assertEqual(list(root.iterdir()), [])

    def test_invalid_names_do_not_modify_worlds_copies_or_staging(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            base = Path(temporary_dir)
            root = base / "worlds"
            root.mkdir()
            current = root / "Asgard"
            current.mkdir()
            (current / "save.db").write_bytes(b"old")
            staged = base / "staged"
            staged.mkdir()
            (staged / "save.db").write_bytes(b"new")
            archive = base / "world.zip"
            archive.write_bytes(b"verified zip")
            for name in ("", "..", "../outside", "a/b", "NUL.txt", "Mundo.", "Mundo "):
                for operation in (
                    lambda: backup_world(root, name),
                    lambda: install_staged_world(root, name, staged),
                    lambda: save_world_copy(root, name, 1, "a" * 64, archive),
                ):
                    with self.subTest(name=name), self.assertRaises(InvalidWorldNameError):
                        operation()
                self.assertEqual([path.name for path in root.iterdir()], ["Asgard"])
                self.assertEqual((current / "save.db").read_bytes(), b"old")
                self.assertEqual((staged / "save.db").read_bytes(), b"new")

    def test_copy_preserves_a_valid_name_longer_than_the_old_truncation_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            source = root / "source.zip"
            source.write_bytes(b"verified zip")
            name = "Peña del Dragón " + "a" * 80
            copy = save_world_copy(root, name, 3, "a" * 64, source)
            self.assertEqual(copy.name, f"{name}_v3_{'a' * 12}.zip")
            self.assertEqual(copy.read_bytes(), source.read_bytes())
            self.assertFalse((root / STATE_FILENAME).exists())

    def test_copy_rejects_unsafe_metadata_before_creating_the_copies_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            source = root / "source.zip"
            source.write_bytes(b"zip")
            for version, sha256 in (("../../outside", "a" * 64), (True, "a" * 64), (0, "a" * 64), (1, "../outside")):
                with self.subTest(version=version, sha256=sha256), self.assertRaises(ValueError):
                    save_world_copy(root, "Asgard", version, sha256, source)
                self.assertFalse((root / COPIES_DIRECTORY_NAME).exists())

    def test_oversized_copy_filename_is_rejected_before_creating_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            source = root / "source.zip"
            source.write_bytes(b"zip")
            with self.assertRaisesRegex(RuntimeError, "255 unidades UTF-16"):
                save_world_copy(root, "a" * 250, 1, "a" * 64, source)
            self.assertEqual(list(root.iterdir()), [source])

    def test_backup_does_not_overwrite_an_existing_backup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            world = root / "Peña del Dragón"
            with patch("bifrost.local_worlds.datetime") as clock:
                clock.now.return_value.strftime.return_value = "20260101-120000"
                world.mkdir()
                (world / "save.db").write_bytes(b"first")
                first = backup_world(root, "PEÑA DEL DRAGÓN")
                world.mkdir()
                (world / "save.db").write_bytes(b"second")
                second = backup_world(root, "Peña del Dragón")
            self.assertEqual(first.name, "Peña del Dragón_pre_pull_20260101-120000")
            self.assertEqual(second.name, "Peña del Dragón_pre_pull_20260101-120000_1")
            self.assertEqual((first / "save.db").read_bytes(), b"first")
            self.assertEqual((second / "save.db").read_bytes(), b"second")

    def test_install_preserves_actual_case_and_restores_original_on_move_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            base = Path(temporary_dir)
            root = base / "worlds"
            root.mkdir()
            world = root / "Peña del Dragón"
            world.mkdir()
            (world / "save.db").write_bytes(b"old")
            staged = base / "staged"
            staged.mkdir()
            (staged / "save.db").write_bytes(b"new")
            real_move = shutil.move

            def failing_move(source, destination):
                """Falla al instalar después de completar el backup y permite restaurarlo."""
                if Path(source) == staged:
                    raise OSError("fallo de instalación simulado")
                return real_move(source, destination)

            with patch("bifrost.local_worlds.shutil.move", side_effect=failing_move):
                with self.assertRaisesRegex(OSError, "simulado"):
                    install_staged_world(root, "PEÑA DEL DRAGÓN", staged)
            self.assertEqual((world / "save.db").read_bytes(), b"old")
            self.assertEqual([path.name for path in root.iterdir()], ["Peña del Dragón"])
            self.assertEqual((staged / "save.db").read_bytes(), b"new")
            backup = install_staged_world(root, "PEÑA DEL DRAGÓN", staged)
            self.assertEqual((world / "save.db").read_bytes(), b"new")
            self.assertEqual((backup / "save.db").read_bytes(), b"old")

    def test_missing_or_overlapping_staging_does_not_move_the_original(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            world = root / "Asgard"
            world.mkdir()
            (world / "save.db").write_bytes(b"old")
            child = world / "staged"
            child.mkdir()
            for staged in (root / "missing", world, child, root):
                with self.subTest(staged=staged), self.assertRaises(RuntimeError):
                    install_staged_world(root, "Asgard", staged)
            self.assertEqual((world / "save.db").read_bytes(), b"old")
            self.assertEqual([path.name for path in root.iterdir()], ["Asgard"])

    def test_install_does_not_move_staging_into_an_existing_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            base = Path(temporary_dir)
            root = base / "worlds"
            root.mkdir()
            destination = root / "Asgard"
            destination.write_bytes(b"existing file")
            staged = base / "staged"
            staged.mkdir()
            (staged / "save.db").write_bytes(b"new")
            with self.assertRaisesRegex(RuntimeError, "ya está ocupado"):
                install_staged_world(root, "Asgard", staged)
            self.assertEqual(destination.read_bytes(), b"existing file")
            self.assertEqual((staged / "save.db").read_bytes(), b"new")

    def test_unsafe_staging_is_rejected_before_creating_a_backup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            base = Path(temporary_dir)
            root = base / "worlds"
            root.mkdir()
            world = root / "Asgard"
            world.mkdir()
            (world / "save.db").write_bytes(b"old")
            staged = base / "staged"
            staged.mkdir()
            outside = base / "outside"
            outside.mkdir()
            make_directory_link(staged / "linked", outside)
            with self.assertRaisesRegex(RuntimeError, "enlace o junction"):
                install_staged_world(root, "Asgard", staged)
            self.assertEqual((world / "save.db").read_bytes(), b"old")
            self.assertEqual(list(root.iterdir()), [world])

    def test_unsafe_backup_destination_is_rejected_before_moving_the_world(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            base = Path(temporary_dir)
            root = base / "worlds"
            root.mkdir()
            world = root / "Asgard"
            world.mkdir()
            (world / "save.db").write_bytes(b"old")
            outside = base / "outside"
            outside.mkdir()
            make_directory_link(root / "Asgard_pre_pull_20260101-120000", outside)
            with patch("bifrost.local_worlds.datetime") as clock:
                clock.now.return_value.strftime.return_value = "20260101-120000"
                with self.assertRaisesRegex(RuntimeError, "enlace o junction"):
                    backup_world(root, "Asgard")
            self.assertEqual((world / "save.db").read_bytes(), b"old")
            self.assertEqual(list(outside.iterdir()), [])

    def test_world_link_is_reported_without_modifying_its_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            base = Path(temporary_dir)
            root = base / "worlds"
            root.mkdir()
            outside = base / "outside"
            outside.mkdir()
            (outside / "save.db").write_bytes(b"outside")
            make_directory_link(root / "Asgard", outside)
            (root / "Bifröst").mkdir()
            errors = []
            self.assertEqual([world.name for world in list_worlds(root, errors=errors)], ["Bifröst"])
            self.assertEqual(errors[0].name, "Asgard")
            self.assertIn("enlace o junction", errors[0].reason)
            for operation in (find_world, backup_world):
                with self.assertRaises(InvalidWorldNameError):
                    operation(root, "Asgard")
            self.assertEqual((outside / "save.db").read_bytes(), b"outside")

    def test_nested_link_blocks_zip_before_replacing_an_existing_archive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            base = Path(temporary_dir)
            world = base / "Asgard"
            world.mkdir()
            outside = base / "outside"
            outside.mkdir()
            (outside / "private.db").write_bytes(b"outside")
            make_directory_link(world / "linked", outside)
            archive = base / "world.zip"
            archive.write_bytes(b"previous archive")
            with self.assertRaisesRegex(RuntimeError, "enlace o junction"):
                create_zip(world, archive)
            self.assertEqual(archive.read_bytes(), b"previous archive")
            self.assertEqual((outside / "private.db").read_bytes(), b"outside")

    def test_copies_directory_link_cannot_write_outside_the_worlds_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            base = Path(temporary_dir)
            root = base / "worlds"
            root.mkdir()
            outside = base / "outside"
            outside.mkdir()
            make_directory_link(root / COPIES_DIRECTORY_NAME, outside)
            source = base / "source.zip"
            source.write_bytes(b"zip")
            with self.assertRaisesRegex(RuntimeError, "enlace o junction"):
                save_world_copy(root, "Asgard", 1, "a" * 64, source)
            self.assertEqual(list(outside.iterdir()), [])

    def test_links_inside_the_root_are_rejected_too(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            (root / "Bifröst").mkdir()
            make_directory_link(root / "Asgard", root / "Bifröst")
            with self.assertRaisesRegex(RuntimeError, "enlace o junction"):
                ensure_local_path(root, root / "Asgard")


class LocalStateSafetyTests(unittest.TestCase):
    def write_state(self, root: Path, worlds: dict) -> Path:
        """Escribe un registro falso para comprobar casos heredados de nombres inválidos."""
        path = root / STATE_FILENAME
        path.write_text(json.dumps({"schema_version": 1, "worlds": worlds}), encoding="utf-8")
        return path

    def test_invalid_names_are_rejected_before_reading_or_writing_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            for name in ("", "../outside", "NUL", "Asgard "):
                with self.subTest(name=name):
                    with self.assertRaises(InvalidWorldNameError):
                        read_base_version(root, name)
                    with self.assertRaises(InvalidWorldNameError):
                        save_base_version(root, name, 1, "a" * 64)
            self.assertEqual(list(root.iterdir()), [])

    def test_conflicting_base_entries_are_not_selected_or_merged(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            state = self.write_state(root, {
                "Asgard": {"version": 1, "sha256": "a" * 64},
                "asgard": {"version": 2, "sha256": "b" * 64},
            })
            original = state.read_bytes()
            with self.assertRaises(WorldNameConflictError):
                read_base_version(root, "ASGARD")
            with self.assertRaises(WorldNameConflictError):
                save_base_version(root, "Asgard", 3, "c" * 64)
            self.assertEqual(state.read_bytes(), original)
            self.assertEqual(list(root.iterdir()), [state])

    def test_other_invalid_or_conflicting_entries_do_not_block_a_valid_world(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            worlds = {
                "../outside": {"legacy": True},
                "Asgard": {"version": 1, "sha256": "a" * 64},
                "asgard": {"version": 2, "sha256": "b" * 64},
                "Peña del Dragón": {"version": 3, "sha256": "c" * 64},
            }
            state = self.write_state(root, worlds)
            self.assertEqual(read_base_version(root, "PEÑA DEL DRAGÓN")["version"], 3)
            save_base_version(root, "PEÑA DEL DRAGÓN", 4, "d" * 64)
            saved = json.loads(state.read_text(encoding="utf-8"))["worlds"]
            self.assertEqual(set(saved), set(worlds))
            for name in ("../outside", "Asgard", "asgard"):
                self.assertEqual(saved[name], worlds[name])
            self.assertEqual(saved["Peña del Dragón"]["version"], 4)

    def test_state_file_link_is_rejected_before_reading_or_creating_temporaries(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            state = self.write_state(root, {"Asgard": {"version": 1, "sha256": "a" * 64}})
            original = state.read_bytes()
            real_lstat = Path.lstat

            def linked_metadata(path, *args, **kwargs):
                """Simula un enlace de archivo sin depender de privilegios de Windows."""
                if path == state:
                    return Mock(st_mode=stat.S_IFLNK, st_reparse_tag=None)
                return real_lstat(path, *args, **kwargs)

            with patch.object(Path, "lstat", linked_metadata):
                with self.assertRaisesRegex(RuntimeError, "enlace o junction"):
                    read_base_version(root, "Asgard")
                with self.assertRaisesRegex(RuntimeError, "enlace o junction"):
                    save_base_version(root, "Asgard", 2, "b" * 64)
            self.assertEqual(state.read_bytes(), original)
            self.assertEqual(list(root.iterdir()), [state])

    def test_failed_state_replacement_keeps_original_and_cleans_the_temporary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            state = self.write_state(root, {"Asgard": {"version": 1, "sha256": "a" * 64}})
            original = state.read_bytes()
            with patch.object(Path, "replace", side_effect=OSError("fallo simulado")):
                with self.assertRaisesRegex(OSError, "simulado"):
                    save_base_version(root, "Asgard", 2, "b" * 64)
            self.assertEqual(state.read_bytes(), original)
            self.assertEqual(list(root.iterdir()), [state])

    def test_failed_state_serialization_keeps_original_and_cleans_the_temporary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            state = self.write_state(root, {"Asgard": {"version": 1, "sha256": "a" * 64}})
            original = state.read_bytes()
            with patch("bifrost.local_state.json.dump", side_effect=OSError("fallo simulado")):
                with self.assertRaisesRegex(OSError, "simulado"):
                    save_base_version(root, "Asgard", 2, "b" * 64)
            self.assertEqual(state.read_bytes(), original)
            self.assertEqual(list(root.iterdir()), [state])


if __name__ == "__main__":
    unittest.main()
