import hashlib
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from botocore.exceptions import ClientError, EndpointConnectionError

from bifrost.cli import restore_menu
from bifrost.config import Settings
from bifrost.local_state import save_base_version
from bifrost.locks import build_lock
from bifrost.paths import state_key, version_manifest_key, version_upload_zip_key
from bifrost.world_names import filter_world_names

from test_restoration import RestorationStorage, zip_bytes


class MenuRestorationStorage(RestorationStorage):
    def list_worlds(self, *, errors=None):
        names = {key.split("/")[1] for key in self.objects if key.startswith("worlds/")}
        return filter_world_names(sorted(names), errors=errors)


class RestoreMenuTests(unittest.TestCase):
    def setUp(self) -> None:
        self.world = "Peña del Dragón"
        self.storage = MenuRestorationStorage()
        self.historical = self.add_publication(5, zip_bytes(), author="Lucía")
        self.current = self.add_publication(8, zip_bytes(content=b"progreso vigente"))
        self.state_key = state_key(self.world)
        self.storage.seed(
            self.state_key,
            {"schema_version": 1, "revision": 12, "manifest": self.current, "lock": None},
        )
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        local_world = self.root / self.world
        local_world.mkdir()
        (local_world / "save.db2").write_bytes(b"progreso local sin publicar")
        save_base_version(self.root, self.world, 8, self.current["sha256"])
        self.settings = Settings("url", "id", "secret", "bucket", self.root, "Taiel")
        self.local_before = self.local_files()

    def add_publication(self, version, payload, *, author="Lucas"):
        filename = version_upload_zip_key(self.world, version, f"published-{version}")
        manifest = {
            "world": self.world, "version": version, "filename": filename,
            "size": len(payload), "sha256": hashlib.sha256(payload).hexdigest(),
            "uploaded_by": author, "uploaded_at": "2026-09-30T22:15:00Z",
        }
        self.storage.seed(filename, payload)
        self.storage.seed(version_manifest_key(self.world, version), manifest)
        return manifest

    def local_files(self):
        return {
            path.relative_to(self.root): path.read_bytes()
            for path in self.root.rglob("*") if path.is_file()
        }

    def render_menu(self, answers=("1", "1", "s")):
        output = io.StringIO()
        with redirect_stdout(output), patch("builtins.input", side_effect=answers) as user_input:
            restore_menu(self.settings, self.storage)
        return output.getvalue(), user_input

    def assert_untouched(self, before):
        self.assertEqual(self.storage.objects, before)
        self.assertEqual(self.local_files(), self.local_before)
        self.assertEqual(self.storage.downloads, [])
        self.assertEqual(self.storage.uploads, [])
        self.assertEqual(self.storage.deleted, [])
        self.assertFalse(any(event[0] in {"conditional", "copy"} for event in self.storage.events))

    def test_shows_history_metadata_and_confirms_global_effect_before_any_mutation(self):
        before = deepcopy(self.storage.objects)
        answers = iter(("1", "1", "s"))
        output = io.StringIO()
        def answer(prompt):
            self.assert_untouched(before)
            if "[s/n]" in prompt:
                self.assertIn(self.world, prompt)
                self.assertIn("contenido de la versión 5", prompt)
                self.assertIn("todo el grupo", prompt)
                shown = output.getvalue()
                self.assertIn("nueva versión 9", shown)
                self.assertIn("Tus archivos locales permanecerán sin cambios", shown)
            return next(answers)

        with redirect_stdout(output), patch("builtins.input", side_effect=answer):
            restore_menu(self.settings, self.storage)

        shown = output.getvalue()
        self.assertIn("Versión 5, fecha 2026-09-30 22:15 UTC, subido por Lucía", shown)
        self.assertIn(f"{self.historical['size']} bytes", shown)
        self.assertIn("publicado como versión 9", shown)
        self.assertIn("'Descargar para hostear' antes de hostear o subir progreso", shown)
        restored = self.storage.objects[self.state_key]["manifest"]
        self.assertEqual(restored["version"], 9)
        self.assertEqual(restored["uploaded_by"], "Taiel")
        self.assertEqual(restored["sha256"], self.historical["sha256"])
        self.assertEqual(self.local_files(), self.local_before)

    def test_can_select_an_older_publication_and_ignores_orphan_and_future_objects(self):
        self.add_publication(7, zip_bytes(content=b"version siete"))
        self.storage.seed(version_upload_zip_key(self.world, 6, "orphan"), b"incompleto")
        self.storage.seed(version_manifest_key(self.world, 10), b"publicacion futura")

        output, _ = self.render_menu(("1", "2", "s"))

        self.assertLess(output.index("Versión 7,"), output.index("Versión 5,"))
        self.assertNotIn("Versión 6,", output)
        self.assertNotIn("Versión 10,", output)
        self.assertIn("contenido de la versión 5 publicado como versión 9", output)

    def test_cancelling_at_every_stage_preserves_world_base_lock_and_all_remote_objects(self):
        expired = build_lock("Otro", machine="PC", now=self.old_date())
        self.storage.seed(
            self.state_key, {**self.storage.objects[self.state_key], "lock": expired}
        )
        for answers in (("0",), ("1", "0"), ("1", "1", "n"), ("1", "1", ""), ("1", "1", "si")):
            with self.subTest(answers=answers):
                before = deepcopy(self.storage.objects)
                output, user_input = self.render_menu(answers)
                self.assertIn("Operación cancelada.", output)
                self.assertEqual(user_input.call_count, len(answers))
                self.assert_untouched(before)

    @staticmethod
    def old_date():
        from datetime import datetime, timezone
        return datetime(2000, 1, 1, tzinfo=timezone.utc)

    def test_invalid_selections_are_cancelled_without_mutations(self):
        for answers in (("x",), ("9",), ("-1",), ("1", "x"), ("1", "9"), ("1", "-1")):
            with self.subTest(answers=answers):
                before = deepcopy(self.storage.objects)
                output, _ = self.render_menu(answers)
                self.assertIn("Opción inválida.", output)
                self.assert_untouched(before)

    def test_empty_cloud_does_not_request_input(self):
        self.storage.objects.clear()
        self.storage.etags.clear()
        output, user_input = self.render_menu(())
        self.assertIn("No hay mundos legibles", output)
        user_input.assert_not_called()

    def test_world_without_current_manifest_does_not_offer_restoration(self):
        self.storage.seed(self.state_key, {**self.storage.objects[self.state_key], "manifest": None})
        before = deepcopy(self.storage.objects)
        output, user_input = self.render_menu(())
        self.assertIn("No hay mundos legibles", output)
        user_input.assert_not_called()
        self.assert_untouched(before)

    def test_absent_published_history_does_not_treat_orphan_archives_as_versions(self):
        self.storage.delete(version_manifest_key(self.world, 5))
        self.storage.deleted.clear()
        before = deepcopy(self.storage.objects)
        output, user_input = self.render_menu(("1",))
        self.assertIn("no tiene versiones anteriores publicadas", output)
        self.assertEqual(user_input.call_count, 1)
        self.assert_untouched(before)

    def test_bad_historical_metadata_blocks_before_version_selection_or_confirmation(self):
        key = version_manifest_key(self.world, 5)
        self.storage.seed(key, {**self.historical, "sha256": "mal"})
        before = deepcopy(self.storage.objects)
        output, user_input = self.render_menu(("1",))
        self.assertIn("SHA-256", output)
        self.assertEqual(user_input.call_count, 1)
        self.assert_untouched(before)

    def test_bad_current_metadata_blocks_before_history_selection(self):
        self.storage.seed(
            self.state_key,
            {**self.storage.objects[self.state_key], "manifest": {**self.current, "sha256": "mal"}},
        )
        before = deepcopy(self.storage.objects)
        output, user_input = self.render_menu(("1",))
        self.assertIn("SHA-256", output)
        self.assertEqual(user_input.call_count, 1)
        self.assert_untouched(before)

    def test_own_foreign_and_invalid_locks_block_without_override_confirmation(self):
        for lock in (
            build_lock("Taiel", machine="PC"), build_lock("Otro", machine="PC"), {},
            {"expires_at": "2000-01-01T00:00:00Z"},
        ):
            with self.subTest(lock=lock):
                self.storage.seed(
                    self.state_key, {**self.storage.objects[self.state_key], "lock": lock}
                )
                before = deepcopy(self.storage.objects)
                output, user_input = self.render_menu(("1",))
                self.assertIn("no se puede restaurar", output)
                self.assertEqual(user_input.call_count, 1)
                self.assert_untouched(before)

    def test_changes_during_confirmation_use_original_etag_and_preserve_concurrent_state(self):
        initial = deepcopy(self.storage.objects[self.state_key])
        for change in (
            {"lock": build_lock("Otro", machine="PC")},
            {"manifest": {**self.current, "version": 9,
                          "filename": version_upload_zip_key(self.world, 9, "winner")}},
        ):
            with self.subTest(change=change):
                self.storage.seed(self.state_key, initial)
                original_etag = self.storage.etags[self.state_key]
                winner = {**initial, **change, "revision": 13}
                answers = iter(("1", "1", "s"))
                def answer(prompt):
                    if "[s/n]" in prompt:
                        self.storage.seed(self.state_key, winner)
                    return next(answers)
                output, _ = self.render_menu(answer)
                self.assertIn("[CONFLICTO]", output)
                self.assertNotIn("[OK]", output)
                self.assertEqual(self.storage.objects[self.state_key], winner)
                self.assertIn(("conditional", self.state_key, original_etag), self.storage.events)
                self.assertNotIn(self.storage.uploads[-1], self.storage.objects)
                self.assertEqual(self.local_files(), self.local_before)

    def test_post_commit_history_warning_is_reported_alongside_success_and_pull_instructions(self):
        def failed_history(key, value):
            if key == version_manifest_key(self.world, 9):
                raise OSError("historial inaccesible")
        self.storage.before_history_write = failed_history
        output, _ = self.render_menu()
        self.assertIn("[OK]", output)
        self.assertIn("[ADVERTENCIA]", output)
        self.assertIn("no se pudo registrar su historial", output)
        self.assertNotIn("Operación cancelada", output)
        self.assertIn("'Descargar para hostear'", output)
        self.assertEqual(self.storage.objects[self.state_key]["manifest"]["version"], 9)

    def test_uncertain_commit_response_does_not_claim_cancellation_or_success(self):
        def lost_response(key, value):
            raise TimeoutError("respuesta perdida")
        self.storage.after_state_write = lost_response
        output, _ = self.render_menu()
        self.assertIn("No se pudo confirmar la publicación", output)
        self.assertIn("Consultá el estado remoto antes de reintentar", output)
        self.assertNotIn("[OK]", output)
        self.assertNotIn("[BLOQUEADO]", output)
        self.assertNotIn("Operación cancelada", output)
        published = self.storage.objects[self.state_key]["manifest"]
        self.assertIn(published["filename"], self.storage.objects)

    def test_reports_unreadable_zip_and_integrity_failures_without_crashing(self):
        key = version_manifest_key(self.world, 5)
        original = deepcopy(self.historical)
        for payload, manifest, message in (
            (b"archivo distinto", original, "SHA-256"),
            (b"no es ZIP", {**original, "size": 9,
                           "sha256": hashlib.sha256(b"no es ZIP").hexdigest()}, "dañado"),
        ):
            with self.subTest(payload=payload):
                self.storage.seed(self.historical["filename"], payload)
                self.storage.seed(key, manifest)
                before = deepcopy(self.storage.objects)
                output, _ = self.render_menu()
                self.assertIn(message, output)
                self.assertNotIn("[OK]", output)
                self.assertEqual(self.storage.objects, before)
                self.assertEqual(self.storage.uploads, [])
                self.assertEqual(self.local_files(), self.local_before)

    def test_missing_zip_is_reported_separately_from_access_failures(self):
        for code, message in (("NoSuchKey", "no está disponible"), ("AccessDenied", "acceso a R2")):
            with self.subTest(code=code):
                self.storage.download_error = ClientError(
                    {"Error": {"Code": code, "Message": "dato-privado-ficticio"}}, "GetObject"
                )
                before = deepcopy(self.storage.objects)
                output, _ = self.render_menu()
                self.assertIn(message, output)
                self.assertNotIn("dato-privado-ficticio", output)
                self.assertEqual(self.storage.objects, before)

    def test_read_access_and_network_errors_return_to_menu_without_exposing_details(self):
        for error, message in (
            (ClientError({"Error": {"Code": "AccessDenied", "Message": "dato-privado-ficticio"}},
                         "ListObjectsV2"), "permisos"),
            (EndpointConnectionError(endpoint_url="https://dato-privado-ficticio.invalid"),
             "conexión"),
        ):
            with self.subTest(error=type(error).__name__):
                before = deepcopy(self.storage.objects)
                with patch.object(self.storage, "list_worlds", side_effect=error):
                    output, user_input = self.render_menu(())
                self.assertIn(message, output)
                self.assertNotIn("dato-privado-ficticio", output)
                user_input.assert_not_called()
                self.assert_untouched(before)

    def test_restore_never_reads_or_writes_local_base_or_installation_helpers(self):
        with (
            patch("bifrost.cli.read_base_version") as read_base,
            patch("bifrost.cli.save_base_version") as save_base,
            patch("bifrost.cli.install_staged_world") as install,
            patch("bifrost.cli.list_worlds") as list_local,
        ):
            self.render_menu()
        read_base.assert_not_called()
        save_base.assert_not_called()
        install.assert_not_called()
        list_local.assert_not_called()
        self.assertEqual(self.local_files(), self.local_before)

    def test_success_displays_removed_history_versions(self):
        for version in (1, 2, 3, 4, 6, 7):
            self.add_publication(version, zip_bytes(content=b"otra version"))
        output, _ = self.render_menu(("1", "3", "s"))
        self.assertIn("Versiones antiguas eliminadas: 1, 2, 3.", output)
        self.assertIn("contenido de la versión 5 publicado como versión 9", output)


if __name__ == "__main__":
    unittest.main()
