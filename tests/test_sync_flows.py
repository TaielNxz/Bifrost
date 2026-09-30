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
from bifrost.storage import ConcurrentUpdateError


class FakeStorage:
    def __init__(self, manifest=None) -> None:
        self.events: list[str] = []
        self.manifest = manifest
        self.world_lock = None
        self.objects: dict[str, object] = {}
        self.etags: dict[str, str] = {}
        self.etag_counter = 0

    def read_manifest(self, world_name):
        return self.manifest

    def upload_file(self, local_path, key):
        self.events.append("zip")
        self.objects[key] = Path(local_path).read_bytes()

    def write_manifest(self, world_name, manifest):
        self.events.append("manifest")
        self.manifest = manifest

    def read_lock(self, world_name):
        return self.world_lock

    def get_json(self, key):
        if key.endswith("/manifest.json") and "/versions/" not in key:
            return self.manifest
        if key.endswith("/lock.json"):
            return self.world_lock
        return self.objects.get(key)

    def get_json_with_etag(self, key):
        return self.objects.get(key), self.etags.get(key)

    def put_json_conditional(self, key, value, expected_etag):
        current_etag = self.etags.get(key)
        if current_etag != expected_etag:
            raise ConcurrentUpdateError("conflict")
        self.etag_counter += 1
        etag = f'"etag-{self.etag_counter}"'
        self.objects[key] = value
        self.etags[key] = etag
        self.manifest = value["manifest"]
        self.world_lock = value["lock"]
        self.events.append("state")
        return etag

    def put_json(self, key, value):
        self.events.append("history_manifest")
        self.objects[key] = value

    def copy(self, source_key, destination_key):
        self.events.append("history_zip")
        self.objects[destination_key] = self.objects.get(source_key, b"current zip")

    def list_keys(self, prefix):
        return [key for key in self.objects if key.startswith(prefix)]

    def delete(self, key):
        self.objects.pop(key, None)


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
            self.assertEqual(storage.events, ["zip", "state", "history_manifest"])
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

            self.assertEqual(
                storage.events,
                ["history_zip", "history_manifest", "zip", "state", "history_manifest"],
            )
            self.assertEqual(storage.manifest["version"], 11)
            self.assertEqual(read_base_version(root, "Asgard")["version"], 11)
            archived_manifest = storage.objects["worlds/Asgard/versions/10/manifest.json"]
            self.assertEqual(archived_manifest["version"], 10)
            self.assertEqual(
                archived_manifest["filename"], "worlds/Asgard/versions/10/world.zip"
            )

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

            self.assertEqual(
                storage.events,
                ["history_zip", "history_manifest", "zip", "state", "history_manifest"],
            )
            self.assertIsNone(storage.world_lock)

    def test_push_blocks_same_player_with_different_session(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            world = root / "Asgard"
            world.mkdir()
            (world / "save.db2").write_bytes(b"local progress")
            manifest = {
                "version": 10,
                "world": "Asgard",
                "filename": "worlds/Asgard/versions/10/id/world.zip",
                "size": 100,
                "sha256": "a" * 64,
                "uploaded_by": "Taiel",
                "uploaded_at": "2020-01-01T00:00:00Z",
            }
            storage = FakeStorage(manifest)
            state_key = "worlds/Asgard/state.json"
            storage.objects[state_key] = {
                "schema_version": 1,
                "revision": 11,
                "manifest": manifest,
                "lock": {
                    "player": "Taiel",
                    "machine": "OTRA-PC",
                    "acquired_at": "2099-01-01T00:00:00Z",
                    "expires_at": "2099-01-01T12:00:00Z",
                    "session_id": "remote-session",
                },
            }
            storage.etags[state_key] = '"etag-1"'
            save_base_version(
                root, "Asgard", 10, "a" * 64, session_id="local-session"
            )
            settings = Settings("url", "id", "secret", "bucket", root, "Taiel")
            output = io.StringIO()

            with redirect_stdout(output), patch("builtins.input", side_effect=["1", "s"]):
                push_menu(settings, storage)  # type: ignore[arg-type]

            self.assertNotIn("zip", storage.events)
            self.assertIn("pertenece a otra sesión tuya", output.getvalue())

    def test_push_conditional_commit_rejects_concurrent_change(self) -> None:
        class ChangingStateStorage(FakeStorage):
            def put_json_conditional(self, key, value, expected_etag):
                raise ConcurrentUpdateError("conflict")

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
            storage = ChangingStateStorage(remote_manifest)
            output = io.StringIO()

            with redirect_stdout(output), patch("builtins.input", side_effect=["1", "s"]):
                push_menu(settings, storage)  # type: ignore[arg-type]

            self.assertEqual(storage.manifest["version"], 10)
            self.assertNotIn("state", storage.events)
            self.assertFalse(
                any("/versions/11/" in key for key in storage.objects)
            )
            self.assertIn("versión oficial no se modificó", output.getvalue())

    def test_push_keeps_only_five_previous_remote_versions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            world = root / "Asgard"
            world.mkdir()
            (world / "save.db2").write_bytes(b"local progress")
            remote_manifest = {
                "version": 6,
                "world": "Asgard",
                "filename": "worlds/Asgard/current/world.zip",
                "size": 100,
                "sha256": "f" * 64,
                "uploaded_by": "Taiel",
                "uploaded_at": "2020-01-01T00:00:00Z",
            }
            save_base_version(root, "Asgard", 6, "f" * 64)
            settings = Settings("url", "id", "secret", "bucket", root, "Taiel")
            storage = FakeStorage(remote_manifest)
            for version in range(1, 6):
                prefix = f"worlds/Asgard/versions/{version}"
                storage.objects[f"{prefix}/world.zip"] = b"old"
                storage.objects[f"{prefix}/manifest.json"] = {"version": version}

            with patch("builtins.input", side_effect=["1", "s"]):
                push_menu(settings, storage)  # type: ignore[arg-type]

            history_keys = storage.list_keys("worlds/Asgard/versions/")
            history_versions = {int(key.split("/")[3]) for key in history_keys}
            self.assertEqual(history_versions, {2, 3, 4, 5, 6, 7})
            self.assertEqual(storage.manifest["version"], 7)

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

            def put_json_conditional(self, key, value, expected_etag):
                self.lock = value["lock"]
                return '"etag-1"'

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
            storage = PullStorage(archive, manifest)

            with patch("builtins.input", side_effect=["1", "s"]):
                pull_menu(settings, storage)  # type: ignore[arg-type]

            self.assertEqual((worlds_root / "Asgard" / "save.db2").read_bytes(), b"remote progress")
            local_base = read_base_version(worlds_root, "Asgard")
            self.assertEqual(local_base["version"], 12)
            self.assertEqual(local_base["sha256"], sha256)
            self.assertEqual(local_base["session_id"], storage.lock["session_id"])

    def test_pull_does_not_download_if_lock_commit_loses_race(self) -> None:
        class ConcurrentPullStorage:
            downloaded = False

            def list_worlds(self):
                return ["Asgard"]

            def read_manifest(self, world_name):
                return {
                    "version": 12,
                    "world": "Asgard",
                    "filename": "worlds/Asgard/versions/12/id/world.zip",
                    "size": 100,
                    "sha256": "a" * 64,
                    "uploaded_by": "Lucas",
                    "uploaded_at": "2026-09-30T22:15:00Z",
                }

            def read_lock(self, world_name):
                return None

            def put_json_conditional(self, key, value, expected_etag):
                raise ConcurrentUpdateError("conflict")

            def download_file(self, key, destination):
                self.downloaded = True
                return Path(destination)

        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            storage = ConcurrentPullStorage()
            settings = Settings("url", "id", "secret", "bucket", root, "Taiel")
            output = io.StringIO()

            with redirect_stdout(output), patch("builtins.input", side_effect=["1", "s"]):
                pull_menu(settings, storage)  # type: ignore[arg-type]

            self.assertFalse(storage.downloaded)
            self.assertIn("cambió antes de adquirir el lock", output.getvalue())

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
                    "filename": "worlds/Asgard/current/world.zip",
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
