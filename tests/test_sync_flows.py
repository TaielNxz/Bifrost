import hashlib
import io
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from bifrost.archives import create_zip
from bifrost.cli import copy_menu, pull_menu, push_menu
from bifrost.config import Settings
from bifrost.local_state import read_base_version, save_base_version
from bifrost.local_worlds import COPIES_DIRECTORY_NAME


class FakeStorage:
    def __init__(self, manifest=None) -> None:
        self.events: list[str] = []
        self.manifest = manifest

    def read_manifest(self, world_name):
        return self.manifest

    def upload_file(self, local_path, key):
        self.events.append("zip")

    def write_manifest(self, world_name, manifest):
        self.events.append("manifest")
        self.manifest = manifest

    def read_lock(self, world_name):
        return None


class LockStorage(FakeStorage):
    def __init__(self, manifest, world_lock) -> None:
        super().__init__(manifest)
        self.world_lock = world_lock

    def read_lock(self, world_name):
        return self.world_lock

    def delete_lock(self, world_name):
        self.events.append("unlock")
        self.world_lock = None


class SyncFlowTests(unittest.TestCase):
    def test_push_publishes_zip_before_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            world = root / "Asgard"
            world.mkdir()
            (world / "save.db2").write_bytes(b"save")
            settings = Settings("url", "id", "secret", "bucket", root, "Taiel")
            storage = FakeStorage()
            output = io.StringIO()
            with redirect_stdout(output), patch("builtins.input", side_effect=["1", "s"]):
                push_menu(settings, storage)  # type: ignore[arg-type]
            self.assertEqual(storage.events, ["zip", "manifest"])
            self.assertEqual(storage.manifest["uploaded_by"], "Taiel")
            self.assertEqual(read_base_version(root, "Asgard")["version"], 1)
            self.assertIn("Asgard          (4 bytes,", output.getvalue())
            self.assertRegex(output.getvalue(), r"Subiendo ZIP de \d+(?:\.\d)? (?:bytes|KB)\.\.\.")

    def test_push_accepts_matching_base_and_updates_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            world = root / "Asgard"
            world.mkdir()
            (world / "save.db2").write_bytes(b"new progress")
            remote_manifest = {
                "version": 10,
                "world": "Asgard",
                "filename": "worlds/Asgard/current/world.zip",
                "size": 100,
                "sha256": "a" * 64,
                "uploaded_by": "Lucas",
                "uploaded_at": "2020-01-01T00:00:00Z",
            }
            save_base_version(root, "Asgard", 10, "a" * 64)
            settings = Settings("url", "id", "secret", "bucket", root, "Taiel")
            storage = FakeStorage(remote_manifest)

            with patch("builtins.input", side_effect=["1", "s"]):
                push_menu(settings, storage)  # type: ignore[arg-type]

            self.assertEqual(storage.events, ["zip", "manifest"])
            self.assertEqual(storage.manifest["version"], 11)
            self.assertEqual(read_base_version(root, "Asgard")["version"], 11)

    def test_push_blocks_outdated_base(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            world = root / "Asgard"
            world.mkdir()
            (world / "save.db2").write_bytes(b"divergent progress")
            remote_manifest = {
                "version": 11,
                "world": "Asgard",
                "filename": "worlds/Asgard/current/world.zip",
                "size": 100,
                "sha256": "b" * 64,
                "uploaded_by": "Lucas",
                "uploaded_at": "2026-09-30T22:15:00Z",
            }
            save_base_version(root, "Asgard", 10, "a" * 64)
            settings = Settings("url", "id", "secret", "bucket", root, "Taiel")
            storage = FakeStorage(remote_manifest)
            output = io.StringIO()

            with redirect_stdout(output), patch("builtins.input", side_effect=["1", "s"]):
                push_menu(settings, storage)  # type: ignore[arg-type]

            self.assertEqual(storage.events, [])
            self.assertIn("Base local: versión 10", output.getvalue())
            self.assertIn("Remoto:     versión 11", output.getvalue())
            self.assertIn("subida fue bloqueada", output.getvalue())

    def test_push_blocks_remote_world_without_local_base(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            world = root / "Asgard"
            world.mkdir()
            (world / "save.db2").write_bytes(b"unknown base")
            remote_manifest = {
                "version": 3,
                "world": "Asgard",
                "filename": "worlds/Asgard/current/world.zip",
                "size": 100,
                "sha256": "c" * 64,
                "uploaded_by": "Lucas",
                "uploaded_at": "2026-09-30T22:15:00Z",
            }
            settings = Settings("url", "id", "secret", "bucket", root, "Taiel")
            storage = FakeStorage(remote_manifest)
            output = io.StringIO()

            with redirect_stdout(output), patch("builtins.input", side_effect=["1", "s"]):
                push_menu(settings, storage)  # type: ignore[arg-type]

            self.assertEqual(storage.events, [])
            self.assertIn("No hay una versión base registrada", output.getvalue())

    def test_push_blocks_same_version_with_different_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            world = root / "Asgard"
            world.mkdir()
            (world / "save.db2").write_bytes(b"local progress")
            remote_manifest = {
                "version": 10,
                "world": "Asgard",
                "filename": "worlds/Asgard/current/world.zip",
                "size": 100,
                "sha256": "b" * 64,
                "uploaded_by": "Lucas",
                "uploaded_at": "2026-09-30T22:15:00Z",
            }
            save_base_version(root, "Asgard", 10, "a" * 64)
            settings = Settings("url", "id", "secret", "bucket", root, "Taiel")
            storage = FakeStorage(remote_manifest)

            with patch("builtins.input", side_effect=["1", "s"]):
                push_menu(settings, storage)  # type: ignore[arg-type]

            self.assertEqual(storage.events, [])

    def test_push_blocks_missing_remote_manifest_when_local_base_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            world = root / "Asgard"
            world.mkdir()
            (world / "save.db2").write_bytes(b"local progress")
            save_base_version(root, "Asgard", 10, "a" * 64)
            settings = Settings("url", "id", "secret", "bucket", root, "Taiel")
            storage = FakeStorage()

            with patch("builtins.input", side_effect=["1", "s"]):
                push_menu(settings, storage)  # type: ignore[arg-type]

            self.assertEqual(storage.events, [])

    def test_push_blocks_foreign_active_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            world = root / "Asgard"
            world.mkdir()
            (world / "save.db2").write_bytes(b"local progress")
            remote_manifest = {
                "version": 10,
                "world": "Asgard",
                "filename": "worlds/Asgard/current/world.zip",
                "size": 100,
                "sha256": "a" * 64,
                "uploaded_by": "Lucas",
                "uploaded_at": "2020-01-01T00:00:00Z",
            }
            world_lock = {
                "player": "Lucas",
                "machine": "PC-LUCAS",
                "acquired_at": "2099-01-01T00:00:00Z",
                "expires_at": "2099-01-01T12:00:00Z",
            }
            save_base_version(root, "Asgard", 10, "a" * 64)
            settings = Settings("url", "id", "secret", "bucket", root, "Taiel")
            storage = LockStorage(remote_manifest, world_lock)
            output = io.StringIO()

            with redirect_stdout(output), patch("builtins.input", side_effect=["1", "s"]):
                push_menu(settings, storage)  # type: ignore[arg-type]

            self.assertEqual(storage.events, [])
            self.assertIn("está siendo usado por otro jugador", output.getvalue())
            self.assertIn("Lucas (PC-LUCAS)", output.getvalue())

    def test_push_with_own_lock_succeeds_and_releases_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            world = root / "Asgard"
            world.mkdir()
            (world / "save.db2").write_bytes(b"local progress")
            remote_manifest = {
                "version": 10,
                "world": "Asgard",
                "filename": "worlds/Asgard/current/world.zip",
                "size": 100,
                "sha256": "a" * 64,
                "uploaded_by": "Taiel",
                "uploaded_at": "2020-01-01T00:00:00Z",
            }
            world_lock = {
                "player": "Taiel",
                "machine": "PC-TAIEL",
                "acquired_at": "2099-01-01T00:00:00Z",
                "expires_at": "2099-01-01T12:00:00Z",
            }
            save_base_version(root, "Asgard", 10, "a" * 64)
            settings = Settings("url", "id", "secret", "bucket", root, "Taiel")
            storage = LockStorage(remote_manifest, world_lock)

            with patch("builtins.input", side_effect=["1", "s"]):
                push_menu(settings, storage)  # type: ignore[arg-type]

            self.assertEqual(storage.events, ["zip", "manifest", "unlock"])
            self.assertIsNone(storage.world_lock)

    def test_push_rechecks_lock_before_upload(self) -> None:
        class ChangingLockStorage(FakeStorage):
            def __init__(self, manifest) -> None:
                super().__init__(manifest)
                self.lock_reads = 0

            def read_lock(self, world_name):
                self.lock_reads += 1
                if self.lock_reads == 1:
                    return None
                return {
                    "player": "Lucas",
                    "machine": "PC-LUCAS",
                    "acquired_at": "2099-01-01T00:00:00Z",
                    "expires_at": "2099-01-01T12:00:00Z",
                }

        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            world = root / "Asgard"
            world.mkdir()
            (world / "save.db2").write_bytes(b"local progress")
            remote_manifest = {
                "version": 10,
                "world": "Asgard",
                "filename": "worlds/Asgard/current/world.zip",
                "size": 100,
                "sha256": "a" * 64,
                "uploaded_by": "Taiel",
                "uploaded_at": "2020-01-01T00:00:00Z",
            }
            save_base_version(root, "Asgard", 10, "a" * 64)
            settings = Settings("url", "id", "secret", "bucket", root, "Taiel")
            storage = ChangingLockStorage(remote_manifest)

            with patch("builtins.input", side_effect=["1", "s"]):
                push_menu(settings, storage)  # type: ignore[arg-type]

            self.assertEqual(storage.events, [])
            self.assertEqual(storage.lock_reads, 2)

    def test_pull_list_displays_manifest_size_in_readable_format(self) -> None:
        class PullStorage:
            def list_worlds(self):
                return ["Asgard"]

            def read_manifest(self, world_name):
                return {
                    "version": 12,
                    "size": 88_709_530,
                    "uploaded_at": "2026-09-30T22:15:00Z",
                    "uploaded_by": "Taiel",
                }

        settings = Settings("url", "id", "secret", "bucket", Path("."), "Taiel")
        output = io.StringIO()
        with redirect_stdout(output), patch("builtins.input", return_value="0"):
            pull_menu(settings, PullStorage())  # type: ignore[arg-type]

        self.assertIn("versión 12, 84.6 MB,", output.getvalue())

    def test_pull_records_downloaded_version_as_local_base(self) -> None:
        class PullStorage:
            def __init__(self, archive: Path, manifest) -> None:
                self.archive = archive
                self.manifest = manifest
                self.lock = None

            def list_worlds(self):
                return ["Asgard"]

            def read_manifest(self, world_name):
                return self.manifest

            def read_lock(self, world_name):
                return self.lock

            def write_lock(self, world_name, world_lock):
                self.lock = world_lock

            def download_file(self, key, destination):
                return Path(shutil.copyfile(self.archive, destination))

        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            worlds_root = root / "worlds"
            worlds_root.mkdir()
            source = root / "remote-source"
            source.mkdir()
            (source / "save.db2").write_bytes(b"remote progress")
            archive = create_zip(source, root / "world.zip")
            sha256 = hashlib.sha256(archive.read_bytes()).hexdigest()
            manifest = {
                "version": 12,
                "world": "Asgard",
                "filename": "worlds/Asgard/current/world.zip",
                "size": archive.stat().st_size,
                "sha256": sha256,
                "uploaded_by": "Lucas",
                "uploaded_at": "2026-09-30T22:15:00Z",
            }
            settings = Settings("url", "id", "secret", "bucket", worlds_root, "Taiel")

            with patch("builtins.input", side_effect=["1", "s"]):
                pull_menu(settings, PullStorage(archive, manifest))  # type: ignore[arg-type]

            self.assertEqual((worlds_root / "Asgard" / "save.db2").read_bytes(), b"remote progress")
            self.assertEqual(
                read_base_version(worlds_root, "Asgard"),
                {"version": 12, "sha256": sha256},
            )

    def test_copy_downloads_verified_zip_without_lock_or_local_replacement(self) -> None:
        class CopyStorage:
            def __init__(self, archive: Path, manifest) -> None:
                self.archive = archive
                self.manifest = manifest

            def list_worlds(self):
                return ["Asgard"]

            def read_manifest(self, world_name):
                return self.manifest

            def download_file(self, key, destination):
                return Path(shutil.copyfile(self.archive, destination))

        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            worlds_root = root / "worlds"
            worlds_root.mkdir()
            active_world = worlds_root / "Asgard"
            active_world.mkdir()
            (active_world / "save.db2").write_bytes(b"local progress")
            source = root / "remote-source"
            source.mkdir()
            (source / "save.db2").write_bytes(b"remote progress")
            archive = create_zip(source, root / "world.zip")
            sha256 = hashlib.sha256(archive.read_bytes()).hexdigest()
            manifest = {
                "version": 12,
                "world": "Asgard",
                "filename": "worlds/Asgard/current/world.zip",
                "size": archive.stat().st_size,
                "sha256": sha256,
                "uploaded_by": "Lucas",
                "uploaded_at": "2026-09-30T22:15:00Z",
            }
            settings = Settings("url", "id", "secret", "bucket", worlds_root, "Taiel")
            output = io.StringIO()

            with redirect_stdout(output), patch("builtins.input", side_effect=["1", "s"]):
                copy_menu(settings, CopyStorage(archive, manifest))  # type: ignore[arg-type]

            copies = list((worlds_root / COPIES_DIRECTORY_NAME).glob("*.zip"))
            self.assertEqual(len(copies), 1)
            self.assertEqual(copies[0].read_bytes(), archive.read_bytes())
            self.assertEqual((active_world / "save.db2").read_bytes(), b"local progress")
            self.assertIsNone(read_base_version(worlds_root, "Asgard"))
            self.assertIn("No se adquirió ningún lock", output.getvalue())

    def test_copy_rejects_corrupted_download(self) -> None:
        class CorruptedStorage:
            def list_worlds(self):
                return ["Asgard"]

            def read_manifest(self, world_name):
                return {
                    "version": 4,
                    "size": 100,
                    "sha256": "a" * 64,
                    "uploaded_at": "2026-09-30T22:15:00Z",
                    "uploaded_by": "Lucas",
                }

            def download_file(self, key, destination):
                path = Path(destination)
                path.write_bytes(b"corrupted")
                return path

        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            output = io.StringIO()
            settings = Settings("url", "id", "secret", "bucket", root, "Taiel")

            with redirect_stdout(output), patch("builtins.input", side_effect=["1", "s"]):
                copy_menu(settings, CorruptedStorage())  # type: ignore[arg-type]

            self.assertFalse((root / COPIES_DIRECTORY_NAME).exists())
            self.assertIn("no coincide con el manifest", output.getvalue())


if __name__ == "__main__":
    unittest.main()
