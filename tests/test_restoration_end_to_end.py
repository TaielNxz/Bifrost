import hashlib
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from zipfile import ZIP_STORED, ZipFile

from botocore.exceptions import ClientError

from bifrost.cli import copy_menu, pull_menu, push_menu, restore_menu, run_menu
from bifrost.config import Settings
from bifrost.local_state import STATE_FILENAME, read_base_version, save_base_version
from bifrost.local_worlds import COPIES_DIRECTORY_NAME, list_worlds
from bifrost.locks import build_lock
from bifrost.paths import (
    current_zip_key,
    manifest_key,
    state_key,
    version_manifest_key,
    version_upload_zip_key,
    version_zip_key,
)
from bifrost.remote_state import read_world_state
from bifrost.storage import R2Storage

from test_world_names_end_to_end import MemoryS3Client


def archive_bytes(files):
    """Prepara un mundo falso con rutas relativas arbitrarias y contenido verificable."""
    stream = io.BytesIO()
    with ZipFile(stream, "w", compression=ZIP_STORED) as archive:
        for relative, content in sorted(files.items()):
            archive.writestr(relative, content)
    return stream.getvalue()


class RestoreS3Client(MemoryS3Client):
    """Registra las precondiciones recibidas por el adaptador real e inyecta una carrera."""

    def __init__(self):
        super().__init__()
        self.conditions = []
        self.before_state_write = None

    def put_object(self, *, Bucket, Key, Body, ContentType, IfMatch=None, IfNoneMatch=None):
        self.conditions.append((Key, IfMatch, IfNoneMatch))
        if Key.endswith("/state.json") and self.before_state_write is not None:
            self.before_state_write(Key, Body)
        return super().put_object(
            Bucket=Bucket, Key=Key, Body=Body, ContentType=ContentType,
            IfMatch=IfMatch, IfNoneMatch=IfNoneMatch,
        )

    def download_fileobj(self, bucket, key, file):
        if key not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        super().download_fileobj(bucket, key, file)


class RestorationEndToEndTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.worlds = self.root / "mundos locales"
        self.worlds.mkdir()
        self.name = "Peña del Dragón"
        self.world = self.worlds / self.name
        (self.world / "datos del mundo").mkdir(parents=True)
        (self.world / "save.db").write_bytes(b"progreso local sin publicar")
        (self.world / "datos del mundo" / "árbol.bin").write_bytes(b"datos locales")
        self.settings = Settings(
            "https://example.invalid", "test-id", "test-secret", "test-bucket",
            self.worlds, "Taiel",
        )
        self.client = RestoreS3Client()
        self.storage = R2Storage(self.settings, client=self.client)
        self.files = {
            "save.db": b"progreso recuperado",
            "datos del mundo/árbol.bin": b"datos historicos",
            "datos del mundo/notas.txt": b"archivo de extension arbitraria",
        }
        self.manifests = {}
        for version in range(1, 9):
            files = self.files if version == 5 else {"save.db": f"version {version}".encode()}
            payload = archive_bytes(files)
            filename = version_upload_zip_key(self.name, version, f"published-{version}")
            manifest = self.metadata(version, filename, payload)
            self.manifests[version] = manifest
            self.client.seed(filename, payload)
            self.client.seed_json(version_manifest_key(self.name, version), manifest)
        self.state_key = state_key(self.name)
        self.client.seed_json(
            self.state_key,
            {"schema_version": 1, "revision": 12, "manifest": self.manifests[8], "lock": None},
        )
        save_base_version(self.worlds, self.name, 8, self.manifests[8]["sha256"])
        copies = self.worlds / COPIES_DIRECTORY_NAME
        copies.mkdir()
        (copies / "copia anterior.zip").write_bytes(archive_bytes({"save.db": b"copia independiente"}))
        self.local_before = self.local_files(self.worlds)

    def metadata(self, version, filename, payload):
        return {
            "version": version, "world": self.name, "filename": filename,
            "size": len(payload), "sha256": hashlib.sha256(payload).hexdigest(),
            "uploaded_by": "Lucía", "uploaded_at": "2020-01-01T00:00:00Z",
        }

    @staticmethod
    def local_files(root):
        return {
            path.relative_to(root): path.read_bytes()
            for path in root.rglob("*") if path.is_file()
        }

    def action(self, menu, answers, settings=None):
        with redirect_stdout(io.StringIO()) as output, patch("builtins.input", side_effect=answers):
            menu(settings or self.settings, self.storage)
        return output.getvalue()

    def current(self):
        return read_world_state(self.storage, self.name).value

    def test_restore_copy_stale_push_host_and_republish_preserve_content_and_session(self):
        """Recorre CLI, dominio, filesystem y adaptador S3 desde la recuperación hasta el push."""
        old_objects = dict(self.client.objects)
        original_etag = self.client.etags[self.state_key]
        orphan = version_upload_zip_key(self.name, 9, "interrupted-upload")
        self.client.seed(orphan, b"candidato incompleto")

        output = self.action(run_menu, ("6", "1", "3", "s", "7"))

        self.assertIn("contenido de la versión 5 publicado como versión 9", output)
        restored = self.current()["manifest"]
        self.assertEqual(restored["version"], 9)
        self.assertEqual(restored["uploaded_by"], "Taiel")
        self.assertNotEqual(restored["uploaded_at"], self.manifests[5]["uploaded_at"])
        self.assertEqual(restored["sha256"], self.manifests[5]["sha256"])
        historical_bytes = old_objects[self.manifests[5]["filename"]]
        self.assertEqual(self.client.objects[restored["filename"]], historical_bytes)
        self.assertEqual(self.local_files(self.worlds), self.local_before)
        self.assertEqual(self.client.objects[orphan], b"candidato incompleto")
        self.assertEqual(self.current()["revision"], 13)
        self.assertIsNone(self.current()["lock"])
        self.assertIn((self.state_key, original_etag, None), self.client.conditions)
        self.assertIn((version_manifest_key(self.name, 9), None, "*"), self.client.conditions)
        self.assertEqual(
            self.client.mutations[:3],
            [("zip", restored["filename"]), ("json", self.state_key),
             ("json", version_manifest_key(self.name, 9))],
        )
        for version in range(1, 4):
            self.assertFalse(any(key.startswith(f"worlds/{self.name}/versions/{version}/")
                                 for key in self.client.objects))
        for version in range(4, 9):
            key = version_manifest_key(self.name, version)
            self.assertEqual(self.client.objects[key], old_objects[key])

        # Una copia de la nueva vigente no habilita a subir desde la base anterior.
        remote_before = dict(self.client.objects)
        base_before = (self.worlds / STATE_FILENAME).read_bytes()
        self.assertIn("Copia verificada", self.action(copy_menu, ("1", "s")))
        copied = self.worlds / COPIES_DIRECTORY_NAME / (
            f"{self.name}_v9_{restored['sha256'][:12]}.zip"
        )
        self.assertEqual(copied.read_bytes(), historical_bytes)
        self.assertEqual((self.worlds / STATE_FILENAME).read_bytes(), base_before)
        self.assertEqual(self.client.objects, remote_before)
        offset = len(self.client.mutations)
        blocked = self.action(push_menu, ("1", "s"))
        self.assertIn("[CONFLICTO]", blocked)
        self.assertIn("no parte de la versión remota vigente", blocked)
        self.assertEqual(self.client.objects, remote_before)
        self.assertEqual(len(self.client.mutations), offset)

        # Hostear instala el contenido recuperado, conserva el progreso previo y registra la sesión.
        previous_world = self.local_files(self.world)
        os.utime(self.world, (1_577_836_800, 1_577_836_800))
        self.assertIn("descargado y verificado", self.action(pull_menu, ("1", "s")))
        self.assertEqual(self.local_files(self.world), {Path(key): value for key, value in self.files.items()})
        backups = list(self.worlds.glob(f"{self.name}_pre_pull_*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(self.local_files(backups[0]), previous_world)
        hosted = self.current()
        base = read_base_version(self.worlds, self.name)
        self.assertEqual(base["version"], 9)
        self.assertEqual(base["sha256"], restored["sha256"])
        self.assertEqual(base["session_id"], hosted["lock"]["session_id"])
        self.assertEqual(hosted["lock"]["base_version"], 9)
        self.assertEqual(hosted["manifest"], restored)
        self.assertEqual(copied.read_bytes(), historical_bytes)

        # El push normal exige esa base y sesión, publica otro ZIP y libera el lock atómicamente.
        (self.world / "save.db").write_bytes(b"progreso posterior a la restauracion")
        offset = len(self.client.mutations)
        self.assertIn("versión 10", self.action(push_menu, ("1", "s", "s")))
        published = self.current()
        latest = published["manifest"]
        self.assertEqual(latest["version"], 10)
        self.assertNotEqual(latest["filename"], restored["filename"])
        self.assertIsNone(published["lock"])
        self.assertEqual(
            self.client.mutations[offset:offset + 2],
            [("zip", latest["filename"]), ("json", self.state_key)],
        )
        self.assertEqual(read_base_version(self.worlds, self.name),
                         {"version": 10, "sha256": latest["sha256"]})
        with ZipFile(io.BytesIO(self.client.objects[latest["filename"]])) as archive:
            self.assertEqual(archive.read("save.db"), b"progreso posterior a la restauracion")
            self.assertEqual(archive.read("datos del mundo/árbol.bin"), self.files["datos del mundo/árbol.bin"])
            self.assertNotIn(STATE_FILENAME, archive.namelist())
        retained = {
            value["version"]
            for key in self.client.objects if key.endswith("/manifest.json")
            if "/versions/" in key
            for value in [self.storage.get_json(key)]
        }
        self.assertEqual(retained, {5, 6, 7, 8, 9, 10})
        self.assertEqual([world.name for world in list_worlds(self.worlds)], [self.name])

    def test_legacy_current_and_flat_historical_zip_restore_without_overwriting_old_objects(self):
        """Migra la publicación heredada por creación condicional y conserva las ubicaciones previas."""
        self.client.objects.pop(self.state_key)
        self.client.etags.pop(self.state_key)
        key = version_manifest_key(self.name, 8)
        self.client.objects.pop(key)
        self.client.etags.pop(key)
        legacy = {**self.manifests[8], "filename": current_zip_key(self.name)}
        current_bytes = self.client.objects[self.manifests[8]["filename"]]
        self.client.seed(legacy["filename"], current_bytes)
        self.client.seed_json(manifest_key(self.name), legacy)
        existing_candidate = version_zip_key(self.name, 8)
        self.client.seed(existing_candidate, b"candidato anterior")
        historical_bytes = self.client.objects[self.manifests[5]["filename"]]
        flat = version_zip_key(self.name, 5)
        self.client.seed(flat, historical_bytes)
        self.client.seed_json(version_manifest_key(self.name, 5),
                              {**self.manifests[5], "filename": flat})
        legacy_record = self.client.objects[manifest_key(self.name)]
        self.assertTrue(read_world_state(self.storage, self.name).legacy)

        self.assertIn("publicado como versión 9", self.action(restore_menu, ("1", "3", "s")))

        self.assertIn((self.state_key, None, "*"), self.client.conditions)
        self.assertFalse(read_world_state(self.storage, self.name).legacy)
        archived = self.storage.get_json(version_manifest_key(self.name, 8))
        self.assertRegex(archived["filename"], r"/versions/8/[0-9a-f]{32}/world\.zip$")
        self.assertEqual(self.client.objects[archived["filename"]], current_bytes)
        self.assertEqual(self.client.objects[existing_candidate], b"candidato anterior")
        self.assertEqual(self.client.objects[legacy["filename"]], current_bytes)
        self.assertEqual(self.client.objects[manifest_key(self.name)], legacy_record)
        self.assertEqual(self.client.objects[self.current()["manifest"]["filename"]], historical_bytes)
        self.assertEqual(self.local_files(self.worlds), self.local_before)
        os.utime(self.world, (1_577_836_800, 1_577_836_800))
        self.assertIn("descargado y verificado", self.action(pull_menu, ("1", "s")))
        self.assertEqual(self.local_files(self.world), {Path(key): value for key, value in self.files.items()})
        self.assertEqual(read_base_version(self.worlds, self.name)["version"], 9)

    def test_cancellation_through_main_menu_preserves_etags_locks_local_base_and_copies(self):
        """Verifica ausencia de escrituras reales del adaptador en las tres formas de cancelar."""
        expired = build_lock("Lucía", machine="PC", now=datetime(2000, 1, 1, tzinfo=timezone.utc))
        self.client.seed_json(self.state_key, {**self.current(), "lock": expired})
        before = dict(self.client.objects)
        etags = dict(self.client.etags)
        for answers in (("6", "0", "7"), ("6", "1", "0", "7"), ("6", "1", "3", "n", "7")):
            with self.subTest(answers=answers):
                output = self.action(run_menu, answers)
                self.assertIn("Operación cancelada", output)
                self.assertEqual(self.client.objects, before)
                self.assertEqual(self.client.etags, etags)
                self.assertEqual(self.client.mutations, [])
                self.assertEqual(self.client.downloads, [])
                self.assertEqual(self.local_files(self.worlds), self.local_before)

    def test_s3_precondition_conflicts_preserve_concurrent_publication_or_lock(self):
        """Ejercita el 412 del adaptador real y elimina solo el ZIP de la restauración perdedora."""
        before = dict(self.client.objects)
        etags = dict(self.client.etags)
        for change_lock in (True, False):
            with self.subTest(change_lock=change_lock):
                self.client.objects = dict(before)
                self.client.etags = dict(etags)
                self.client.mutations.clear()
                self.client.conditions.clear()
                winner = {}
                def race(key, body):
                    original = json.loads(before[key])
                    if change_lock:
                        value = {**original, "revision": 13, "lock": build_lock("Lucía", machine="PC")}
                    else:
                        filename = version_upload_zip_key(self.name, 9, "winner")
                        payload = archive_bytes({"save.db": b"progreso concurrente"})
                        metadata = self.metadata(9, filename, payload)
                        self.client.seed(filename, payload)
                        self.client.seed_json(version_manifest_key(self.name, 9), metadata)
                        value = {**original, "revision": 13, "manifest": metadata}
                    winner.update(value)
                    self.client.seed_json(key, value)
                self.client.before_state_write = race

                output = self.action(restore_menu, ("1", "3", "s"))

                self.assertIn("[CONFLICTO]", output)
                self.assertEqual(self.current(), winner)
                candidates = [key for kind, key in self.client.mutations if kind == "zip"]
                self.assertEqual(len(candidates), 1)
                self.assertNotIn(candidates[0], self.client.objects)
                self.assertIn(("delete", candidates[0]), self.client.mutations)
                self.assertIn((self.state_key, etags[self.state_key], None), self.client.conditions)
                if not change_lock:
                    self.assertIn(winner["manifest"]["filename"], self.client.objects)
                    self.assertEqual(self.storage.get_json(version_manifest_key(self.name, 9)),
                                     winner["manifest"])
                self.assertEqual(self.local_files(self.worlds), self.local_before)

    def test_invalid_or_missing_history_archives_never_write_through_s3_adapter(self):
        """Comprueba lectura JSON, ausencia S3, SHA-256, rutas y CRC antes de toda mutación."""
        before = dict(self.client.objects)
        etags = dict(self.client.etags)
        historical = self.manifests[5]
        crc_zip = archive_bytes({"save.db": b"crc original"})
        cases = ("missing", "bad_json", "null", "hash", "unsafe", "crc")
        for case in cases:
            with self.subTest(case=case):
                self.client.objects = dict(before)
                self.client.etags = dict(etags)
                if case == "missing":
                    self.client.objects.pop(historical["filename"])
                elif case in {"bad_json", "null"}:
                    self.client.seed(version_manifest_key(self.name, 5), b"{" if case == "bad_json" else b"null")
                elif case == "hash":
                    self.client.seed_json(version_manifest_key(self.name, 5),
                                          {**historical, "sha256": "0" * 64})
                else:
                    payload = (
                        archive_bytes({"../escape.db": b"escape"})
                        if case == "unsafe" else crc_zip.replace(b"crc original", b"crc alterado")
                    )
                    self.client.seed(historical["filename"], payload)
                    self.client.seed_json(version_manifest_key(self.name, 5),
                                          self.metadata(5, historical["filename"], payload))
                prepared = dict(self.client.objects)

                output = self.action(restore_menu, ("1", "3", "s"))

                self.assertNotIn("[OK]", output)
                self.assertEqual(self.client.objects, prepared)
                self.assertEqual(self.client.mutations, [])
                self.assertEqual(self.local_files(self.worlds), self.local_before)

    def test_history_write_failure_after_state_commit_is_success_with_warning(self):
        """Mantiene la publicación oficial aunque falle el registro auxiliar después del commit."""
        original_put = self.client.put_object
        def fail_history(**arguments):
            if arguments["Key"] == version_manifest_key(self.name, 9):
                raise ClientError({"Error": {"Code": "AccessDenied"}}, "PutObject")
            return original_put(**arguments)
        with patch.object(self.client, "put_object", side_effect=fail_history):
            output = self.action(restore_menu, ("1", "3", "s"))
        self.assertIn("[OK]", output)
        self.assertIn("[ADVERTENCIA]", output)
        self.assertIn("no se pudo registrar su historial", output)
        self.assertNotIn("Operación cancelada", output)
        published = self.current()["manifest"]
        self.assertEqual(published["version"], 9)
        self.assertIn(published["filename"], self.client.objects)
        self.assertIsNone(self.storage.get_json(version_manifest_key(self.name, 9)))
        self.assertEqual(self.local_files(self.worlds), self.local_before)


if __name__ == "__main__":
    unittest.main()
