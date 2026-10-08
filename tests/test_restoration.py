import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from botocore.exceptions import ClientError

from bifrost.locks import build_lock
from bifrost.manifests import parse_iso_datetime
from bifrost.paths import (
    current_zip_key,
    manifest_key,
    state_key,
    version_manifest_key,
    version_upload_zip_key,
    version_zip_key,
)
from bifrost.remote_state import StateSnapshot, read_world_state
from bifrost.restoration import restore_world_version
from bifrost.storage import ConcurrentUpdateError
from bifrost.versions import (
    archive_current_version_conditionally,
    record_published_version_if_absent,
)


def zip_bytes(filename="nested/save.db2", content=b"progreso historico"):
    """Construye ZIP falsos; ZIP_STORED permite alterar contenido sin recalcular su CRC."""
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr(filename, content)
    return stream.getvalue()


class RestorationStorage:
    """Simula objetos, lecturas independientes y precondiciones por ETag para cualquier JSON."""

    def __init__(self):
        self.objects = {}
        self.etags = {}
        self.counter = 0
        self.events = []
        self.downloads = []
        self.uploads = []
        self.deleted = []
        self.download_error = None
        self.upload_error = None
        self.delete_error = None
        self.list_error = None
        self.before_state_write = None
        self.after_state_write = None
        self.before_history_write = None

    def seed(self, key, value):
        self.counter += 1
        self.objects[key] = deepcopy(value)
        self.etags[key] = f'"etag-{self.counter}"'
        return self.etags[key]

    def get_json(self, key):
        return self.get_json_with_etag(key)[0]

    def get_json_with_etag(self, key):
        self.events.append(("read", key))
        value = deepcopy(self.objects.get(key))
        if isinstance(value, bytes):
            value = json.loads(value.decode("utf-8"))
        return value, self.etags.get(key)

    def put_json_conditional(self, key, value, expected_etag):
        self.events.append(("conditional", key, expected_etag))
        hook = self.before_state_write if key.endswith("/state.json") else self.before_history_write
        if hook is not None:
            hook(key, value)
        if (
            (expected_etag is None and key in self.objects)
            or (expected_etag is not None and self.etags.get(key) != expected_etag)
        ):
            raise ConcurrentUpdateError("El estado remoto cambió durante la operación.")
        etag = self.seed(key, value)
        self.events.append(("published", key))
        if key.endswith("/state.json") and self.after_state_write is not None:
            self.after_state_write(key, value)
        return etag

    def download_file(self, key, destination):
        self.downloads.append(Path(destination))
        self.events.append(("download", key))
        if self.download_error is not None:
            raise self.download_error
        if key not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        Path(destination).write_bytes(self.objects[key])
        return Path(destination)

    def upload_file(self, local_path, key):
        self.uploads.append(key)
        self.objects[key] = Path(local_path).read_bytes()
        self.events.append(("zip", key))
        if self.upload_error is not None:
            raise self.upload_error

    def copy(self, source_key, destination_key):
        self.objects[destination_key] = self.objects[source_key]
        self.events.append(("copy", destination_key))

    def delete(self, key):
        if self.delete_error is not None:
            raise self.delete_error
        self.deleted.append(key)
        self.events.append(("delete", key))
        self.objects.pop(key, None)
        self.etags.pop(key, None)

    def list_keys(self, prefix):
        if self.list_error is not None:
            raise self.list_error
        return [key for key in self.objects if key.startswith(prefix)]


class RestorationTests(unittest.TestCase):
    def setUp(self):
        self.world = "Ásgard grupo"
        self.storage = RestorationStorage()
        self.historical = self.add_publication(5, zip_bytes())
        self.current = self.add_publication(8, zip_bytes(content=b"progreso vigente"))
        self.state_key = state_key(self.world)
        self.storage.seed(
            self.state_key,
            {"schema_version": 1, "revision": 12, "manifest": self.current, "lock": None},
        )
        self.snapshot = read_world_state(self.storage, self.world)
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.local_root = Path(self.temporary.name)
        local_world = self.local_root / self.world
        local_world.mkdir()
        (local_world / "save.db2").write_bytes(b"progreso local sin publicar")
        (self.local_root / ".bifrost-state.json").write_bytes(b'{"base": "sin cambios"}')
        self.local_before = self.local_files()

    def add_publication(self, version, payload, *, filename=None):
        filename = filename or version_upload_zip_key(self.world, version, f"published-{version}")
        manifest = {
            "world": self.world,
            "version": version,
            "filename": filename,
            "size": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "uploaded_by": "Lucas",
            "uploaded_at": "2020-01-01T00:00:00Z",
        }
        self.storage.seed(filename, payload)
        self.storage.seed(version_manifest_key(self.world, version), manifest)
        return manifest

    def local_files(self):
        return {
            path.relative_to(self.local_root): path.read_bytes()
            for path in self.local_root.rglob("*")
            if path.is_file()
        }

    def restore(self, version=5, snapshot=None, player="Taiel"):
        return restore_world_version(
            self.storage, self.world, version, player,
            snapshot=self.snapshot if snapshot is None else snapshot,
        )

    def assert_no_publication(self, before):
        self.assertEqual(self.storage.objects, before)
        self.assertEqual(self.storage.uploads, [])
        self.assertEqual(self.local_files(), self.local_before)
        self.assertTrue(all(not path.parent.exists() for path in self.storage.downloads))

    def replace_historical_zip(self, payload):
        self.storage.objects[self.historical["filename"]] = payload
        record = self.storage.objects[version_manifest_key(self.world, 5)]
        record.update(size=len(payload), sha256=hashlib.sha256(payload).hexdigest())

    def test_restores_exact_bytes_as_current_plus_one_and_preserves_local_data(self):
        before = deepcopy(self.storage.objects)
        started_at = datetime.now(timezone.utc).replace(microsecond=0)

        result = self.restore()

        manifest = result.manifest
        self.assertEqual(manifest["version"], 9)
        self.assertEqual(manifest["uploaded_by"], "Taiel")
        self.assertGreaterEqual(parse_iso_datetime(manifest["uploaded_at"]), started_at)
        self.assertEqual(manifest["sha256"], self.historical["sha256"])
        self.assertEqual(manifest["size"], self.historical["size"])
        self.assertRegex(manifest["filename"], r"/versions/9/[0-9a-f]{32}/world\.zip$")
        self.assertEqual(
            self.storage.objects[manifest["filename"]], before[self.historical["filename"]]
        )
        state = self.storage.objects[self.state_key]
        self.assertEqual(state, {"schema_version": 1, "revision": 13, "manifest": manifest, "lock": None})
        self.assertEqual(self.storage.objects[version_manifest_key(self.world, 9)], manifest)
        for version in (5, 8):
            key = version_manifest_key(self.world, version)
            self.assertEqual(self.storage.objects[key], before[key])
        self.assertEqual(self.snapshot.value, before[self.state_key])
        self.assertEqual(self.local_files(), self.local_before)
        self.assertEqual(result.warnings, ())
        self.assertEqual(result.removed_versions, ())
        self.assertFalse(self.storage.downloads[0].is_relative_to(self.local_root))
        self.assertFalse(self.storage.downloads[0].parent.exists())
        zip_event = self.storage.events.index(("zip", manifest["filename"]))
        state_event = self.storage.events.index(("published", self.state_key))
        history_event = self.storage.events.index(("published", version_manifest_key(self.world, 9)))
        self.assertLess(zip_event, state_event)
        self.assertLess(state_event, history_event)
        self.assertIn(("conditional", self.state_key, self.snapshot.etag), self.storage.events)

    def test_accepts_historical_zip_without_upload_id(self):
        self.historical = self.add_publication(5, zip_bytes(), filename=version_zip_key(self.world, 5))
        self.assertEqual(self.restore().manifest["version"], 9)

    def test_preserves_current_when_its_history_record_is_missing(self):
        key = version_manifest_key(self.world, 8)
        self.storage.delete(key)
        result = self.restore()
        self.assertEqual(self.storage.objects[key], self.current)
        self.assertLess(
            self.storage.events.index(("published", key)),
            self.storage.events.index(("zip", result.manifest["filename"])),
        )
        self.assertIn(("conditional", key, None), self.storage.events)

    def test_supports_legacy_state_and_preserves_mutable_current_zip_at_unique_key(self):
        self.storage.delete(self.state_key)
        self.storage.delete(version_manifest_key(self.world, 8))
        legacy = {**self.current, "filename": current_zip_key(self.world)}
        current_bytes = self.storage.objects[self.current["filename"]]
        self.storage.seed(legacy["filename"], current_bytes)
        self.storage.seed(manifest_key(self.world), legacy)
        orphan = version_zip_key(self.world, 8)
        self.storage.seed(orphan, b"candidato existente")
        snapshot = read_world_state(self.storage, self.world)

        result = self.restore(snapshot=snapshot)

        self.assertTrue(snapshot.legacy)
        archived = self.storage.objects[version_manifest_key(self.world, 8)]
        self.assertRegex(archived["filename"], r"/versions/8/[0-9a-f]{32}/world\.zip$")
        self.assertEqual(self.storage.objects[archived["filename"]], current_bytes)
        self.assertEqual(self.storage.objects[orphan], b"candidato existente")
        self.assertEqual(self.storage.objects[manifest_key(self.world)], legacy)
        self.assertEqual(result.manifest["version"], 9)
        self.assertIn(("conditional", self.state_key, None), self.storage.events)

    def test_rejects_non_previous_versions_and_invalid_player_before_mutation(self):
        for version in (8, 9, 0, -1, True, "5"):
            with self.subTest(version=version):
                before = deepcopy(self.storage.objects)
                with self.assertRaises((ValueError, RuntimeError)):
                    self.restore(version)
                self.assert_no_publication(before)
        for player in ("", " ", None):
            with self.subTest(player=player):
                before = deepcopy(self.storage.objects)
                with self.assertRaises(RuntimeError):
                    self.restore(player=player)
                self.assert_no_publication(before)

    def test_rejects_snapshot_without_current_manifest_or_valid_cas_data(self):
        changes = (
            {"manifest": None}, {"revision": -1}, {"revision": True},
            {"schema_version": 2}, {"schema_version": True}, {"manifest": {**self.current, "sha256": "mal"}},
        )
        for change in changes:
            with self.subTest(change=change):
                invalid = StateSnapshot({**self.snapshot.value, **change}, self.snapshot.etag)
                before = deepcopy(self.storage.objects)
                with self.assertRaises(RuntimeError):
                    self.restore(snapshot=invalid)
                self.assert_no_publication(before)
        for etag in (None, "", 12):
            with self.subTest(etag=etag):
                before = deepcopy(self.storage.objects)
                with self.assertRaises(RuntimeError):
                    self.restore(snapshot=StateSnapshot(self.snapshot.value, etag))
                self.assert_no_publication(before)

    def test_missing_historical_manifest_blocks_publication(self):
        self.storage.delete(version_manifest_key(self.world, 5))
        before = deepcopy(self.storage.objects)
        with self.assertRaisesRegex(RuntimeError, "manifest histórico.*no está disponible"):
            self.restore()
        self.assert_no_publication(before)

    def test_invalid_historical_metadata_blocks_publication(self):
        key = version_manifest_key(self.world, 5)
        original = deepcopy(self.storage.objects[key])
        invalid_values = [
            None, b"{", [], {**original, "version": 4}, {**original, "size": True},
            {**original, "world": "Otro mundo"}, {**original, "sha256": "incorrecto"},
            {**original, "uploaded_by": ""}, {**original, "uploaded_at": "2020-01-01"},
            {**original, "filename": current_zip_key(self.world)},
            {**original, "filename": version_upload_zip_key("Otro mundo", 5, "id")},
        ]
        for value in invalid_values:
            with self.subTest(value=value):
                self.storage.seed(key, value)
                before = deepcopy(self.storage.objects)
                with self.assertRaises((RuntimeError, ValueError)):
                    self.restore()
                self.assert_no_publication(before)

    def test_missing_zip_differs_from_permission_or_network_failures(self):
        for code, message in (("NoSuchKey", "no está disponible"), ("AccessDenied", "acceso a R2")):
            with self.subTest(code=code):
                self.storage.download_error = ClientError({"Error": {"Code": code}}, "GetObject")
                before = deepcopy(self.storage.objects)
                with self.assertRaisesRegex(RuntimeError, message):
                    self.restore()
                self.assert_no_publication(before)
        self.storage.download_error = TimeoutError("red")
        before = deepcopy(self.storage.objects)
        with self.assertRaises(TimeoutError):
            self.restore()
        self.assert_no_publication(before)

    def test_missing_zip_is_not_an_empty_successful_download(self):
        self.storage.delete(self.historical["filename"])
        before = deepcopy(self.storage.objects)
        with self.assertRaisesRegex(RuntimeError, "ZIP histórico.*no está disponible"):
            self.restore()
        self.assert_no_publication(before)

    def test_hash_and_size_mismatch_block_publication(self):
        key = version_manifest_key(self.world, 5)
        original = deepcopy(self.storage.objects[key])
        for change in ({"sha256": "0" * 64}, {"size": original["size"] + 1}):
            with self.subTest(change=change):
                self.storage.seed(key, {**original, **change})
                before = deepcopy(self.storage.objects)
                with self.assertRaises((ValueError, RuntimeError)):
                    self.restore()
                self.assert_no_publication(before)

    def test_unsafe_unreadable_and_crc_corrupt_archives_block_publication(self):
        good = zip_bytes(content=b"crc original")
        corrupt = good.replace(b"crc original", b"crc alterado")
        for payload in (zip_bytes("../escape.db"), zip_bytes("C:/escape.db"), b"no es ZIP", corrupt):
            with self.subTest(payload=payload):
                self.replace_historical_zip(payload)
                before = deepcopy(self.storage.objects)
                with self.assertRaises((ValueError, zipfile.BadZipFile)):
                    self.restore()
                self.assert_no_publication(before)

    def test_existing_next_history_record_including_null_is_never_overwritten(self):
        for value in (
            {**self.current, "version": 9, "filename": version_zip_key(self.world, 9)},
            {**self.historical, "version": 9, "filename": version_zip_key(self.world, 9)},
            None, b"{",
        ):
            with self.subTest(value=value):
                self.storage.seed(version_manifest_key(self.world, 9), value)
                before = deepcopy(self.storage.objects)
                with self.assertRaises(RuntimeError):
                    self.restore()
                self.assert_no_publication(before)

    def test_invalid_or_conflicting_current_history_blocks_publication(self):
        key = version_manifest_key(self.world, 8)
        for value in (None, b"{", {**self.current, "sha256": "0" * 64}, {**self.current, "uploaded_by": "Otro"}):
            with self.subTest(value=value):
                self.storage.seed(key, value)
                before = deepcopy(self.storage.objects)
                with self.assertRaises(RuntimeError):
                    self.restore()
                self.assert_no_publication(before)

    def test_own_foreign_and_invalid_locks_block_restoration(self):
        for lock in (
            build_lock("Taiel", machine="PC"), build_lock("Otro", machine="PC"),
            {}, {"expires_at": "2000-01-01T00:00:00Z"},
        ):
            with self.subTest(lock=lock):
                self.storage.seed(self.state_key, {**self.snapshot.value, "lock": lock})
                snapshot = read_world_state(self.storage, self.world)
                before = deepcopy(self.storage.objects)
                with self.assertRaisesRegex(RuntimeError, "lock"):
                    self.restore(snapshot=snapshot)
                self.assert_no_publication(before)

    def test_expired_valid_lock_allows_restoration_and_is_cleared_atomically(self):
        lock = build_lock("Taiel", machine="PC", now=datetime.now(timezone.utc) - timedelta(days=1))
        self.storage.seed(self.state_key, {**self.snapshot.value, "lock": lock})
        snapshot = read_world_state(self.storage, self.world)
        self.restore(snapshot=snapshot)
        self.assertIsNone(self.storage.objects[self.state_key]["lock"])

    def test_concurrent_push_or_lock_change_keeps_winner_and_discards_only_own_zip(self):
        for mutation in (
            {"manifest": {**self.current, "version": 9, "filename": version_zip_key(self.world, 9)}},
            {"lock": build_lock("Otro", machine="PC")},
        ):
            with self.subTest(mutation=mutation):
                original = deepcopy(self.snapshot.value)
                self.storage.seed(self.state_key, original)
                snapshot = read_world_state(self.storage, self.world)
                winner = {**original, **mutation, "revision": 13}
                winner_zip = version_upload_zip_key(self.world, 9, "winner")
                self.storage.seed(winner_zip, b"progreso concurrente")
                self.storage.before_state_write = lambda key, value: self.storage.seed(key, winner)
                with self.assertRaises(ConcurrentUpdateError):
                    self.restore(snapshot=snapshot)
                self.assertEqual(self.storage.objects[self.state_key], winner)
                self.assertEqual(self.storage.objects[winner_zip], b"progreso concurrente")
                self.assertNotIn(self.storage.uploads[-1], self.storage.objects)
                self.assertNotIn(version_manifest_key(self.world, 9), self.storage.objects)
                self.assertEqual(self.local_files(), self.local_before)

    def test_two_restorations_use_distinct_candidates_and_only_one_can_commit(self):
        results = []
        def competing_restore(key, value):
            self.storage.before_state_write = None
            results.append(self.restore())
        self.storage.before_state_write = competing_restore

        with self.assertRaises(ConcurrentUpdateError):
            self.restore()

        self.assertEqual(len(results), 1)
        self.assertEqual(len(set(self.storage.uploads)), 2)
        winner = results[0].manifest
        self.assertEqual(self.storage.objects[self.state_key]["manifest"], winner)
        self.assertIn(winner["filename"], self.storage.objects)
        self.assertEqual(len(self.storage.deleted), 1)
        self.assertNotEqual(self.storage.deleted[0], winner["filename"])

    def test_failed_upload_cleans_partial_candidate_and_never_attempts_state_commit(self):
        self.storage.upload_error = OSError("subida fallida")
        before_state = deepcopy(self.storage.objects[self.state_key])
        with self.assertRaises(OSError):
            self.restore()
        self.assertEqual(self.storage.objects[self.state_key], before_state)
        self.assertEqual(self.storage.deleted, self.storage.uploads)
        self.assertFalse(any(event[:2] == ("conditional", self.state_key) for event in self.storage.events))
        self.assertTrue(all(not path.parent.exists() for path in self.storage.downloads))

    def test_conflict_with_cleanup_failure_reports_conflict_and_preserves_winner(self):
        winner = {**self.snapshot.value, "revision": 13, "lock": build_lock("Otro", machine="PC")}
        self.storage.before_state_write = lambda key, value: self.storage.seed(key, winner)
        self.storage.delete_error = OSError("borrado fallido")
        with self.assertRaisesRegex(ConcurrentUpdateError, "No se pudo eliminar"):
            self.restore()
        self.assertEqual(self.storage.objects[self.state_key], winner)
        self.assertIn(self.storage.uploads[-1], self.storage.objects)

    def test_uncertain_commit_response_never_deletes_possibly_published_archive(self):
        def lost_response(key, value):
            raise TimeoutError("respuesta perdida")
        self.storage.after_state_write = lost_response
        with self.assertRaisesRegex(RuntimeError, "No se pudo confirmar"):
            self.restore()
        published = self.storage.objects[self.state_key]["manifest"]
        self.assertEqual(published["version"], 9)
        self.assertIn(published["filename"], self.storage.objects)
        self.assertEqual(self.storage.deleted, [])
        self.assertEqual(self.local_files(), self.local_before)

    def test_history_failure_after_commit_reports_success_with_warning(self):
        def fail_history(key, value):
            if key == version_manifest_key(self.world, 9):
                raise OSError("historial no disponible")
        self.storage.before_history_write = fail_history
        result = self.restore()
        self.assertEqual(self.storage.objects[self.state_key]["manifest"], result.manifest)
        self.assertIn(result.manifest["filename"], self.storage.objects)
        self.assertEqual(len(result.warnings), 1)
        self.assertIn("registrar su historial", result.warnings[0])
        self.assertEqual(self.storage.deleted, [])

    def test_concurrent_history_creation_is_preserved_after_successful_commit(self):
        conflicting = {**self.current, "version": 9, "filename": version_zip_key(self.world, 9)}
        def race_history(key, value):
            if key == version_manifest_key(self.world, 9):
                self.storage.seed(key, conflicting)
        self.storage.before_history_write = race_history
        result = self.restore()
        self.assertEqual(self.storage.objects[version_manifest_key(self.world, 9)], conflicting)
        self.assertEqual(self.storage.objects[self.state_key]["manifest"], result.manifest)
        self.assertEqual(len(result.warnings), 1)

    def test_retains_current_and_five_previous_publications_ignoring_orphan_candidates(self):
        for version in (1, 2, 3, 4, 6, 7):
            self.add_publication(version, zip_bytes(content=f"version {version}".encode()))
        orphan = version_upload_zip_key(self.world, 10, "orphan")
        self.storage.seed(orphan, b"subida incompleta")
        result = self.restore()
        self.assertEqual(result.removed_versions, (1, 2, 3))
        published = {
            value["version"] for key, value in self.storage.objects.items()
            if "/versions/" in key and key.endswith("/manifest.json")
        }
        self.assertEqual(published, {4, 5, 6, 7, 8, 9})
        self.assertIn(orphan, self.storage.objects)
        self.assertIn(result.manifest["filename"], self.storage.objects)

    def test_retention_uses_latest_current_if_another_publication_finishes_after_commit(self):
        for version in (1, 2, 3, 4, 6, 7):
            self.add_publication(version, zip_bytes(content=b"otra version"))
        def newer_publication(key, value):
            newer = self.add_publication(10, zip_bytes(content=b"nuevo progreso"))
            self.storage.seed(key, {**value, "revision": 14, "manifest": newer})
        self.storage.after_state_write = newer_publication
        result = self.restore()
        self.assertEqual(self.storage.objects[self.state_key]["manifest"]["version"], 10)
        self.assertEqual(result.removed_versions, (1, 2, 3, 4))
        self.assertIn(version_manifest_key(self.world, 10), self.storage.objects)
        self.assertEqual(result.warnings, ())

    def test_retention_failure_after_commit_never_undoes_publication(self):
        self.storage.list_error = OSError("listado fallido")
        result = self.restore()
        self.assertEqual(self.storage.objects[self.state_key]["manifest"], result.manifest)
        self.assertEqual(self.storage.objects[version_manifest_key(self.world, 9)], result.manifest)
        self.assertIn(result.manifest["filename"], self.storage.objects)
        self.assertIn("retención", result.warnings[0])


    def test_failed_retention_deletion_keeps_current_and_reports_maintenance_warning(self):
        for version in (1, 2, 3, 4, 6, 7):
            self.add_publication(version, zip_bytes(content=b"otra version"))
        self.storage.delete_error = OSError("borrado fallido")
        result = self.restore()
        self.assertEqual(self.storage.objects[self.state_key]["manifest"], result.manifest)
        self.assertIn(result.manifest["filename"], self.storage.objects)
        self.assertIn("retención", result.warnings[0])

    def test_uncertain_response_before_state_commit_keeps_candidate_without_claiming_success(self):
        before_state = deepcopy(self.storage.objects[self.state_key])
        def unavailable_state(key, value):
            raise TimeoutError("servidor no disponible")
        self.storage.before_state_write = unavailable_state
        with self.assertRaisesRegex(RuntimeError, "No se pudo confirmar"):
            self.restore()
        self.assertEqual(self.storage.objects[self.state_key], before_state)
        self.assertIn(self.storage.uploads[-1], self.storage.objects)
        self.assertEqual(self.storage.deleted, [])
class ConditionalHistoryTests(unittest.TestCase):
    def setUp(self):
        self.storage = RestorationStorage()
        payload = zip_bytes()
        self.manifest = {
            "world": "Asgard", "version": 8,
            "filename": version_upload_zip_key("Asgard", 8, "original"),
            "size": len(payload), "sha256": hashlib.sha256(payload).hexdigest(),
            "uploaded_by": "Taiel", "uploaded_at": "2020-01-01T00:00:00Z",
        }
        self.storage.seed(self.manifest["filename"], payload)
        self.key = version_manifest_key("Asgard", 8)

    def test_creates_history_conditionally_and_preserves_matching_existing_record(self):
        self.assertTrue(record_published_version_if_absent(self.storage, "Asgard", self.manifest))
        etag = self.storage.etags[self.key]
        self.assertFalse(record_published_version_if_absent(self.storage, "Asgard", self.manifest))
        self.assertEqual(self.storage.etags[self.key], etag)
        self.assertEqual(self.storage.objects[self.key], self.manifest)

    def test_history_race_never_overwrites_a_conflicting_record(self):
        other = {**self.manifest, "sha256": "0" * 64}
        self.storage.before_history_write = lambda key, value: self.storage.seed(key, other)
        with self.assertRaisesRegex(RuntimeError, "otra publicación"):
            record_published_version_if_absent(self.storage, "Asgard", self.manifest)
        self.assertEqual(self.storage.objects[self.key], other)

    def test_archival_race_keeps_the_first_matching_legacy_record(self):
        legacy = {**self.manifest, "filename": current_zip_key("Asgard")}
        self.storage.seed(legacy["filename"], self.storage.objects[self.manifest["filename"]])
        self.storage.before_history_write = lambda key, value: self.storage.seed(key, self.manifest)
        self.assertFalse(archive_current_version_conditionally(self.storage, "Asgard", legacy))
        self.assertEqual(self.storage.objects[self.key], self.manifest)
        self.assertIn(self.manifest["filename"], self.storage.objects)


if __name__ == "__main__":
    unittest.main()
