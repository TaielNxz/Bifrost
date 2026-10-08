import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

from botocore.exceptions import ClientError

from bifrost.cli import copy_menu, lock_menu, pull_menu, push_menu, status_menu
from bifrost.config import Settings
from bifrost.local_state import save_base_version
from bifrost.manifests import build_manifest, validate_manifest_identity
from bifrost.paths import (
    backup_key, current_zip_key, lock_key, manifest_key, state_key,
    version_manifest_key, version_prefix, version_upload_zip_key, version_zip_key,
    versions_prefix, world_prefix,
)
from bifrost.remote_state import StateSnapshot, commit_world_state, read_world_state
from bifrost.storage import R2Storage
from bifrost.versions import (
    archive_current_version, prune_remote_versions, read_version_manifest, record_published_version,
)
from bifrost.world_names import filter_world_names


def manifest(name="Asgard", **overrides):
    """Construye un manifest falso permitiendo alterar campos para probar rechazos."""
    return {
        "world": name, "version": 1, "filename": current_zip_key(name),
        "size": 100, "sha256": "a" * 64, "uploaded_by": "Jugador",
        "uploaded_at": "2020-01-01T00:00:00Z", **overrides,
    }


def state(metadata=None):
    """Construye un estado remoto falso con el manifest indicado y sin lock."""
    return {"schema_version": 1, "revision": 1, "manifest": metadata, "lock": None}


class MenuStorage:
    """Simula metadata remota y falla si un menú intenta descargar o modificar objetos."""

    def __init__(self, manifests):
        """Prepara las lecturas falsas y bloquea descargas y modificaciones remotas."""
        self.manifests = manifests
        self.reads = []
        self.put_json_conditional = Mock(side_effect=AssertionError("No debe cambiar el estado"))
        self.download_file = Mock(side_effect=AssertionError("No debe descargar"))
        self.upload_file = Mock(side_effect=AssertionError("No debe subir"))
        self.copy = Mock(side_effect=AssertionError("No debe copiar"))
        self.put_json = Mock(side_effect=AssertionError("No debe publicar"))

    def list_worlds(self, *, errors=None):
        """Lista los nombres remotos falsos excluyendo entradas inválidas o ambiguas."""
        return filter_world_names(self.manifests, errors=errors)

    def get_json_with_etag(self, key):
        """Simula una lectura de estado con ETag y registra la clave consultada.

        Devuelve dos valores None si el mundo no está registrado.
        """
        self.reads.append(key)
        name = key.split("/")[1]

        # Caso 1: El mundo no está registrado; simula la ausencia del estado canónico.
        if name not in self.manifests:
            return None, None

        # Caso 2: El mundo está registrado; devuelve su estado con un ETag ficticio.
        return state(self.manifests[name]), '"etag"'

    def get_json(self, key):
        """Registra la clave consultada y simula un objeto JSON ausente."""
        self.reads.append(key)
        return None


class RemoteNameSafetyTests(unittest.TestCase):
    def test_all_world_keys_reject_unsafe_names(self):
        """Comprueba que todos los constructores de claves rechacen nombres inseguros."""
        builders = (
            state_key, manifest_key, lock_key, current_zip_key, versions_prefix, world_prefix,
            lambda name: version_prefix(name, 1), lambda name: version_zip_key(name, 1),
            lambda name: version_manifest_key(name, 1),
            lambda name: version_upload_zip_key(name, 1, "id"),
            lambda name: backup_key(name, "20261006"),
        )
        for builder in builders:
            for name in ("", "../Otro", "C:\\Mundo", "NUL", "Mundo.", "Asgard/otro", "a\n"):
                with self.subTest(builder=builder, name=name), self.assertRaises(ValueError):
                    builder(name)

    def test_other_key_components_cannot_escape_the_world(self):
        """Comprueba el rechazo de versiones inválidas y segmentos que alterarían la clave."""
        for version in (True, 0, -1, "../Otro"):
            with self.subTest(version=version), self.assertRaises(ValueError):
                version_upload_zip_key("Asgard", version, "id")

        # Comprueba también los segmentos de candidatos y backups, no solo el nombre del mundo.
        for component in ("", "..", "../Otro", "a/b", "a\\b", "C:otro", "a\x00"):
            for builder in (
                lambda: version_upload_zip_key("Asgard", 1, component),
                lambda: backup_key("Asgard", component),
            ):
                with self.subTest(component=component), self.assertRaises(ValueError):
                    builder()

    def test_valid_names_and_all_supported_zip_locations_are_preserved(self):
        """Comprueba que las ubicaciones admitidas conserven la identidad y el manifest original."""
        name = "Peña del Dragón %"
        for filename in (
            current_zip_key(name), version_zip_key(name, 1),
            version_upload_zip_key(name, 1, "candidato-1"),
        ):
            metadata = manifest(name, filename=filename)
            with self.subTest(filename=filename):
                self.assertIs(validate_manifest_identity(name, metadata), metadata)

                # Verifica la misma identidad en el estado canónico y en la lectura heredada.
                for canonical in (False, True):
                    storage = Mock()
                    storage.get_json_with_etag.return_value = (state(metadata), '"etag"') if canonical else (None, None)
                    storage.get_json.side_effect = [metadata, None]
                    snapshot = read_world_state(storage, name)
                    self.assertEqual(snapshot.value["manifest"], metadata)
                    self.assertEqual(snapshot.legacy, not canonical)

    def test_mismatched_or_unsafe_manifest_identity_is_rejected(self):
        """Comprueba que una identidad o clave inválida se rechace sin publicar estado remoto."""
        invalid = (
            {"world": "Otro"}, {"world": "asgard"}, {"world": "../Asgard"},
            {"world": None}, {"filename": "worlds/Otro/current/world.zip"},
            {"filename": "worlds/asgard/current/world.zip"},
            {"filename": "worlds/Asgard/../Otro/world.zip"},
            {"filename": "worlds/Asgard/versions/2/id/world.zip"},
            {"filename": "worlds/Asgard/versions/01/id/world.zip"},
            {"filename": "worlds/Asgard/versions/1/../world.zip"},
            {"filename": "worlds/Asgard/versions/1/a/b/world.zip"},
            {"filename": "worlds/Asgard/versions/1/a\\b/world.zip"},
            {"filename": "worlds/Asgard/versions/1/id/otro.zip"},
            {"filename": "worlds/Asgard/current/world.zip/otro"},
            {"filename": "/worlds/Asgard/current/world.zip"},
            {"filename": "worlds\\Asgard\\current\\world.zip"},
            {"filename": None}, {"filename": ""},
        )
        for overrides in invalid:
            metadata = manifest(**overrides)
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                validate_manifest_identity("Asgard", metadata)

            # Aplica el mismo rechazo a las lecturas canónica y heredada.
            for canonical in (False, True):
                storage = Mock()
                storage.get_json_with_etag.return_value = (state(metadata), '"etag"') if canonical else (None, None)
                storage.get_json.side_effect = [metadata, None]
                with self.subTest(canonical=canonical), self.assertRaises(ValueError):
                    read_world_state(storage, "Asgard")
                storage.put_json_conditional.assert_not_called()

                # Un estado canónico inválido no debe habilitar una lectura heredada como fallback.
                if canonical:
                    storage.get_json.assert_not_called()

    def test_invalid_names_do_not_read_remote_objects(self):
        """Comprueba que los nombres inválidos se rechacen antes de acceder al almacenamiento."""
        storage = Mock()
        with self.assertRaises(ValueError):
            read_world_state(storage, "../Otro")
        self.assertEqual(storage.mock_calls, [])

        # Repite la comprobación en los lectores heredados con un cliente S3 falso.
        settings = Settings("url", "id", "secret", "bucket", Path("."), "Jugador")
        client = Mock()
        storage = R2Storage(settings, client)
        for reader in (storage.read_manifest, storage.read_lock):
            with self.assertRaises(ValueError):
                reader("NUL")
        self.assertEqual(client.mock_calls, [])

    def test_legacy_storage_reader_rejects_mismatched_identity(self):
        """Comprueba que el lector heredado rechace un manifest que declara otro mundo."""
        settings = Settings("url", "id", "secret", "bucket", Path("."), "Jugador")
        storage = R2Storage(settings, Mock())
        with patch.object(storage, "get_json", return_value=manifest(world="Otro")):
            with self.assertRaisesRegex(ValueError, "declara otro mundo"):
                storage.read_manifest("Asgard")

    def test_invalid_outgoing_or_original_state_does_not_commit(self):
        """Comprueba que un estado original o propuesto inválido impida el commit remoto."""
        storage = Mock()
        valid = state(manifest())
        invalid = state(manifest(world="Otro"))
        for original, outgoing in ((valid, invalid), (invalid, valid)):
            with self.subTest(original=original), self.assertRaises(ValueError):
                commit_world_state(storage, "Asgard", StateSnapshot(original, '"etag"'), outgoing)
        storage.put_json_conditional.assert_not_called()

    def test_build_manifest_rejects_identity_before_reading_the_zip(self):
        """Comprueba que una clave ajena se rechace antes de consultar el ZIP de origen."""
        with patch.object(Path, "stat") as read:
            with self.assertRaises(ValueError):
                build_manifest("missing.zip", "Asgard", 1, "Jugador", filename="worlds/Otro/current/world.zip")
        read.assert_not_called()

    def test_history_rejects_unsafe_identity_before_read_or_write(self):
        """Comprueba que las identidades inválidas bloqueen las operaciones del historial."""
        for action in (archive_current_version, record_published_version):
            storage = Mock()

            # Un manifest entrante inválido se rechaza antes de consultar objetos remotos.
            with self.subTest(action=action), self.assertRaises(ValueError):
                action(storage, "Asgard", manifest(filename="worlds/Otro/current/world.zip"))
            self.assertEqual(storage.mock_calls, [])

            # Un registro histórico inválido permite la consulta, pero impide copiar o publicar.
            storage.get_json.return_value = manifest(world="Otro")
            with self.assertRaises(ValueError):
                action(storage, "Asgard", manifest())
            storage.copy.assert_not_called()
            storage.put_json.assert_not_called()

        # Un nombre de mundo inválido también debe impedir la consulta para aplicar retención.
        storage = Mock()
        with self.assertRaises(ValueError):
            prune_remote_versions(storage, "../Otro")
        self.assertEqual(storage.mock_calls, [])

    def test_history_record_must_match_its_version_key(self):
        """Comprueba que la versión declarada coincida con la clave histórica consultada."""
        storage = Mock()
        storage.get_json.return_value = manifest(version=2)
        with self.assertRaisesRegex(ValueError, "declara la versión 2"):
            read_version_manifest(storage, "Asgard", 1)
        storage.put_json.assert_not_called()


class RemoteNameMenuSafetyTests(unittest.TestCase):
    def settings(self, root):
        """Construye la configuración ficticia para operar sobre una carpeta temporal."""
        return Settings("url", "id", "secret", "bucket", root, "Jugador")

    def run_menu(self, menu, root, storage, answers=("1", "s")):
        """Ejecuta un menú y comprueba que no descargue ni modifique objetos remotos.

        Devuelve la salida capturada con respuestas simuladas.
        """
        output = io.StringIO()
        with redirect_stdout(output), patch("builtins.input", side_effect=answers):
            menu(self.settings(root), storage)

        # Comprueba que el bloqueo o la cancelación ocurran antes de descargar o modificar objetos.
        storage.put_json_conditional.assert_not_called()
        storage.download_file.assert_not_called()
        storage.upload_file.assert_not_called()
        storage.copy.assert_not_called()
        storage.put_json.assert_not_called()
        return output.getvalue()

    def test_push_blocks_remote_case_alias_and_conflicting_remote_group(self):
        """Comprueba que las variantes remotas de mayúsculas bloqueen el push sin alterar el mundo."""
        for names in (("asgard",), ("Asgard", "asgard")):
            with self.subTest(names=names), tempfile.TemporaryDirectory() as temporary_dir:
                root = Path(temporary_dir)
                (root / "Asgard").mkdir()
                (root / "Asgard" / "save.db").write_bytes(b"local")
                storage = MenuStorage({name: manifest(name) for name in names})
                output = self.run_menu(push_menu, root, storage)
                self.assertIn("Conflicto entre nombres", output)
                self.assertIn("'Asgard'", output)
                self.assertIn("'asgard'", output)
                self.assertEqual(storage.reads, [])
                self.assertEqual((root / "Asgard" / "save.db").read_bytes(), b"local")
                self.assertEqual(len(list(root.iterdir())), 1)

    def test_push_blocks_invalid_manifest_or_local_base_before_creating_zip(self):
        """Comprueba que un manifest inválido o una base ambigua bloqueen la creación del ZIP."""
        for invalid_manifest in (False, True):
            with self.subTest(invalid_manifest=invalid_manifest), tempfile.TemporaryDirectory() as temporary_dir:
                root = Path(temporary_dir)
                (root / "Asgard").mkdir()

                # Prepara el conflicto local solo cuando se prueba la base, no el manifest remoto.
                if not invalid_manifest:
                    (root / ".bifrost-state.json").write_text(json.dumps({
                        "schema_version": 1, "worlds": {
                            "Asgard": {"version": 1, "sha256": "a" * 64},
                            "asgard": {"version": 1, "sha256": "a" * 64},
                        },
                    }), encoding="utf-8")
                storage = MenuStorage({"Asgard": manifest(world="Otro") if invalid_manifest else manifest()})
                with patch("bifrost.cli.create_zip") as zip_file:
                    output = self.run_menu(push_menu, root, storage)
                zip_file.assert_not_called()
                self.assertIn("[BLOQUEADO]", output)

    def test_push_blocks_existing_next_history_before_any_mutation(self):
        """Comprueba que una identidad inválida en la próxima versión histórica bloquee el push."""
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            (root / "Asgard").mkdir()
            storage = MenuStorage({})
            storage.get_json = Mock(side_effect=lambda key: (
                manifest(world="Otro") if key == "worlds/Asgard/versions/1/manifest.json" else None
            ))
            with patch("bifrost.cli.create_zip") as zip_file:
                output = self.run_menu(push_menu, root, storage)
            zip_file.assert_not_called()
            self.assertIn("declara otro mundo: 'Otro'", output)

    def test_push_blocks_invalid_current_history_before_creating_zip(self):
        """Comprueba que un historial vigente con identidad ajena bloquee la creación del ZIP."""
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            (root / "Asgard").mkdir()
            save_base_version(root, "Asgard", 1, "a" * 64)
            storage = MenuStorage({"Asgard": manifest()})
            storage.get_json = Mock(return_value=manifest(world="Otro"))
            with patch("bifrost.cli.create_zip") as zip_file:
                output = self.run_menu(push_menu, root, storage)
            zip_file.assert_not_called()
            self.assertIn("declara otro mundo: 'Otro'", output)

    def test_pull_checks_local_destination_base_and_case_before_lock(self):
        """Comprueba que los problemas de destino, identidad o base bloqueen el pull antes del lock."""
        for problem in ("file", "case", "base", "backup", "hash"):
            with self.subTest(problem=problem), tempfile.TemporaryDirectory() as temporary_dir:
                root = Path(temporary_dir)
                name = "Asgard"

                # Caso 1: El destino es un archivo; no puede recibir la carpeta del mundo.
                if problem == "file":
                    (root / name).write_bytes(b"occupied")
                # Caso 2: Hay un mundo con otra escritura; simula el conflicto de identidad.
                elif problem == "case":
                    (root / "asgard").mkdir()
                # Caso 3: Hay dos bases coincidentes; simula un registro local ambiguo.
                elif problem == "base":
                    (root / ".bifrost-state.json").write_text(json.dumps({
                        "schema_version": 1, "worlds": {
                            "Asgard": {"version": 1, "sha256": "a" * 64},
                            "asgard": {"version": 1, "sha256": "a" * 64},
                        },
                    }), encoding="utf-8")
                # Caso 4: El nombre es muy largo; el sufijo del backup supera el límite permitido.
                elif problem == "backup":
                    name = "a" * 240
                    (root / name).mkdir()

                # El escenario de hash inválido se prepara en la metadata, sin entradas locales.
                metadata = manifest(name, sha256="unsafe" if problem == "hash" else "a" * 64)
                storage = MenuStorage({name: metadata})
                before = sorted(path.name for path in root.iterdir())

                # Verifica el bloqueo remoto y que la preparación no altere las entradas locales.
                output = self.run_menu(pull_menu, root, storage)
                self.assertIn("[BLOQUEADO]", output)
                self.assertEqual(sorted(path.name for path in root.iterdir()), before)

    def test_copy_checks_occupied_or_oversized_destination_before_download(self):
        """Comprueba que un destino ocupado o demasiado largo bloquee la copia antes de descargar."""
        for problem in ("file", "directory", "length"):
            with self.subTest(problem=problem), tempfile.TemporaryDirectory() as temporary_dir:
                root = Path(temporary_dir)
                name = "a" * 240 if problem == "length" else "Asgard"

                # Caso 1: La carpeta de copias es un archivo; no puede contener la descarga.
                if problem == "file":
                    (root / ".bifrost-copies").write_bytes(b"occupied")
                # Caso 2: El destino del ZIP es una carpeta; no puede reemplazarse como archivo.
                elif problem == "directory":
                    (root / ".bifrost-copies" / f"{name}_v1_{'a' * 12}.zip").mkdir(parents=True)

                # El escenario de longitud usa el nombre extenso sin crear un destino ocupado.
                storage = MenuStorage({name: manifest(name)})
                output = self.run_menu(copy_menu, root, storage)
                self.assertIn("[BLOQUEADO]", output)

                # Un nombre demasiado largo debe rechazarse antes de crear la carpeta de copias.
                if problem == "length":
                    self.assertEqual(list(root.iterdir()), [])

    def test_bad_remote_identity_is_excluded_without_hiding_valid_worlds(self):
        """Comprueba que los menús informen identidades inválidas y conserven los mundos válidos."""
        for menu in (pull_menu, copy_menu, lock_menu):
            with self.subTest(menu=menu), tempfile.TemporaryDirectory() as temporary_dir:
                root = Path(temporary_dir)
                storage = MenuStorage({"Asgard": manifest(world="Otro"), "Peña del Dragón": manifest("Peña del Dragón")})
                output = self.run_menu(menu, root, storage, answers=("0",))
                self.assertIn("declara otro mundo: 'Otro'", output)
                self.assertIn("1) Peña del Dragón", output)
                self.assertNotIn("1) Asgard", output)

        # El menú de estado informa el error y sigue mostrando el mundo válido como libre.
        storage = MenuStorage({"Asgard": manifest(filename="worlds/Otro/current/world.zip"), "Peña del Dragón": manifest("Peña del Dragón")})
        output = io.StringIO()
        with redirect_stdout(output):
            status_menu(storage)
        self.assertIn("ubicación inválida", output.getvalue())
        self.assertIn("Peña del Dragón", output.getvalue())
        self.assertIn("Estado:         Libre", output.getvalue())

    def test_remote_access_failure_is_not_treated_as_a_missing_world(self):
        """Comprueba que un error de permisos se propague sin habilitar descargas o subidas."""
        for menu in (push_menu, pull_menu, copy_menu, lock_menu):
            with self.subTest(menu=menu), tempfile.TemporaryDirectory() as temporary_dir:
                root = Path(temporary_dir)
                (root / "Asgard").mkdir()
                storage = MenuStorage({"Asgard": manifest()})
                storage.get_json_with_etag = Mock(side_effect=ClientError(
                    {"Error": {"Code": "AccessDenied", "Message": "Acceso denegado"}},
                    "GetObject",
                ))
                with self.assertRaises(ClientError):
                    self.run_menu(menu, root, storage)
                storage.put_json_conditional.assert_not_called()
                storage.download_file.assert_not_called()
                storage.upload_file.assert_not_called()


if __name__ == "__main__":
    unittest.main()
