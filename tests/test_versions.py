import json
import unittest
from copy import deepcopy
from unittest.mock import patch

from botocore.exceptions import ClientError

from bifrost.versions import archive_current_version, list_previous_versions, prune_remote_versions


class FakeVersionStorage:
    def __init__(self) -> None:
        self.objects: dict[str, object] = {}
        self.copies: list[tuple[str, str]] = []
        self.deleted: list[str] = []
        self.written: list[str] = []
        self.read_keys: list[str] = []
        self.listed_prefixes: list[str] = []

    def get_json(self, key):
        self.read_keys.append(key)
        return self.objects.get(key)

    def copy(self, source_key, destination_key):
        self.copies.append((source_key, destination_key))
        self.objects[destination_key] = b"zip"

    def put_json(self, key, value):
        self.written.append(key)
        self.objects[key] = value

    def list_keys(self, prefix):
        self.listed_prefixes.append(prefix)
        return [key for key in self.objects if key.startswith(prefix)]

    def delete(self, key):
        self.deleted.append(key)
        del self.objects[key]


def manifest(version: int, sha256: str = "a" * 64) -> dict[str, object]:
    """Construye un manifest remoto mínimo para las pruebas de historial."""
    return {
        "version": version,
        "world": "Asgard",
        "filename": "worlds/Asgard/current/world.zip",
        "size": 100,
        "sha256": sha256,
        "uploaded_by": "Taiel",
        "uploaded_at": "2026-09-30T22:15:00Z",
    }


class RemoteVersionTests(unittest.TestCase):
    def test_archives_zip_before_manifest_and_adjusts_filename(self) -> None:
        storage = FakeVersionStorage()

        created = archive_current_version(storage, "Asgard", manifest(7))  # type: ignore[arg-type]

        self.assertTrue(created)
        self.assertEqual(
            storage.copies,
            [
                (
                    "worlds/Asgard/current/world.zip",
                    "worlds/Asgard/versions/7/world.zip",
                )
            ],
        )
        archived = storage.objects["worlds/Asgard/versions/7/manifest.json"]
        self.assertEqual(archived["filename"], "worlds/Asgard/versions/7/world.zip")

    def test_does_not_overwrite_existing_matching_version(self) -> None:
        storage = FakeVersionStorage()
        storage.objects["worlds/Asgard/versions/7/manifest.json"] = manifest(7)

        created = archive_current_version(storage, "Asgard", manifest(7))  # type: ignore[arg-type]

        self.assertFalse(created)
        self.assertEqual(storage.copies, [])

    def test_rejects_existing_version_with_different_hash(self) -> None:
        storage = FakeVersionStorage()
        storage.objects["worlds/Asgard/versions/7/manifest.json"] = manifest(7, "b" * 64)

        with self.assertRaisesRegex(RuntimeError, "otro hash"):
            archive_current_version(storage, "Asgard", manifest(7))  # type: ignore[arg-type]

    def test_prunes_oldest_versions(self) -> None:
        storage = FakeVersionStorage()
        for version in range(1, 8):
            prefix = f"worlds/Asgard/versions/{version}"
            storage.objects[f"{prefix}/world.zip"] = b"zip"
            storage.objects[f"{prefix}/manifest.json"] = manifest(version)

        removed = prune_remote_versions(storage, "Asgard", keep=5)  # type: ignore[arg-type]

        self.assertEqual(removed, [1, 2])
        self.assertEqual(
            {
                int(key.split("/")[3])
                for key in storage.objects
                if key.startswith("worlds/Asgard/versions/")
            },
            {3, 4, 5, 6, 7},
        )


class PublishedVersionListingTests(unittest.TestCase):
    def setUp(self) -> None:
        """Prepara un historial falso y una versión vigente ya leída."""
        self.storage = FakeVersionStorage()
        self.current = manifest(10)

    def add_version(self, version: int, upload_id: str | None = None) -> dict[str, object]:
        """Agrega un registro publicado con una de las ubicaciones históricas compatibles."""
        value = manifest(version)
        suffix = "world.zip" if upload_id is None else f"{upload_id}/world.zip"
        value["filename"] = f"worlds/Asgard/versions/{version}/{suffix}"
        self.storage.objects[f"worlds/Asgard/versions/{version}/manifest.json"] = value
        self.storage.objects[value["filename"]] = b"zip"
        return value

    def test_empty_history_returns_no_previous_versions(self) -> None:
        """La versión vigente por sí sola no ofrece una versión anterior."""
        self.assertEqual(
            list_previous_versions(self.storage, "Asgard", self.current), []
        )  # type: ignore[arg-type]
        self.assertEqual(self.storage.read_keys, [])

    def test_no_current_manifest_does_not_treat_history_as_published(self) -> None:
        """No deduce una versión vigente a partir de objetos históricos sueltos."""
        self.add_version(5)

        self.assertEqual(
            list_previous_versions(self.storage, "Asgard", None), []
        )  # type: ignore[arg-type]
        self.assertEqual(self.storage.listed_prefixes, [])
        self.assertEqual(self.storage.read_keys, [])

    def test_orders_versions_and_preserves_display_metadata(self) -> None:
        """Ordena numéricamente y conserva fecha, autor, tamaño y ubicación publicada."""
        old = self.add_version(2)
        recent = self.add_version(9, "published-upload")
        middle = self.add_version(5)
        recent.update(size=4096, uploaded_by="Lucía", uploaded_at="2026-10-01T12:00:00Z")

        result = list_previous_versions(
            self.storage, "Asgard", self.current
        )  # type: ignore[arg-type]

        self.assertEqual(result, [recent, middle, old])
        self.assertEqual(
            self.storage.read_keys,
            [
                "worlds/Asgard/versions/9/manifest.json",
                "worlds/Asgard/versions/5/manifest.json",
                "worlds/Asgard/versions/2/manifest.json",
            ],
        )
        self.assertEqual(self.storage.listed_prefixes, ["worlds/Asgard/versions/"])

    def test_ignores_orphans_current_future_and_noncanonical_records(self) -> None:
        """No confunde ZIP candidatos ni claves ajenas con publicaciones anteriores."""
        published = self.add_version(5, "published-upload")
        for key in (
            "worlds/Asgard/versions/5/orphan-upload/world.zip",
            "worlds/Asgard/versions/6/orphan-upload/world.zip",
            "worlds/Asgard/versions/10/manifest.json",
            "worlds/Asgard/versions/11/manifest.json",
            "worlds/Asgard/versions/0/manifest.json",
            "worlds/Asgard/versions/04/manifest.json",
            "worlds/Asgard/versions/-1/manifest.json",
            "worlds/Asgard/versions/²/manifest.json",
            "worlds/Asgard/versions/4/upload-id/manifest.json",
            "worlds/Asgard/versions/4/manifest.json.bak",
        ):
            self.storage.objects[key] = b"unpublished or invalid"

        result = list_previous_versions(
            self.storage, "Asgard", self.current
        )  # type: ignore[arg-type]

        self.assertEqual(result, [published])
        self.assertEqual(self.storage.read_keys, ["worlds/Asgard/versions/5/manifest.json"])

    def test_listing_never_writes_or_mutates_metadata(self) -> None:
        """Mantiene los objetos y la metadata de entrada intactos durante la consulta."""
        published = self.add_version(5)
        published["sha256"] = "A" * 64
        before = deepcopy(self.storage.objects)
        current_before = deepcopy(self.current)

        result = list_previous_versions(
            self.storage, "Asgard", self.current
        )  # type: ignore[arg-type]

        self.assertEqual(result[0]["sha256"], "a" * 64)
        self.assertEqual(self.storage.objects, before)
        self.assertEqual(self.current, current_before)
        self.assertEqual(self.storage.written, [])
        self.assertEqual(self.storage.copies, [])
        self.assertEqual(self.storage.deleted, [])

    def test_accepts_spaces_accents_and_literal_world_prefixes(self) -> None:
        """Consulta nombres compatibles con Windows sin interpretarlos como patrones."""
        world_name = "Mídgard (grupo).+"
        current = {**manifest(10), "world": world_name}
        current["filename"] = f"worlds/{world_name}/versions/10/id/world.zip"
        published = {**manifest(5), "world": world_name}
        published["filename"] = f"worlds/{world_name}/versions/5/world.zip"
        self.storage.objects[f"worlds/{world_name}/versions/5/manifest.json"] = published

        result = list_previous_versions(
            self.storage, world_name, current
        )  # type: ignore[arg-type]

        self.assertEqual(result, [published])

    def test_invalid_current_manifest_blocks_history_lookup(self) -> None:
        """No consulta versiones con una referencia vigente que no puede validarse."""
        with self.assertRaises(RuntimeError):
            list_previous_versions(
                self.storage, "Asgard", {"version": 10}
            )  # type: ignore[arg-type]
        self.assertEqual(self.storage.listed_prefixes, [])
        self.assertEqual(self.storage.read_keys, [])

    def test_invalid_historical_metadata_is_not_silently_skipped(self) -> None:
        """Los registros incompletos o con otro tipo JSON impiden usar el historial."""
        key = "worlds/Asgard/versions/5/manifest.json"
        for value in ([], "manifest", 5, True, {"version": 5}):
            with self.subTest(value=value):
                self.storage.objects[key] = value
                with self.assertRaises(RuntimeError):
                    list_previous_versions(
                        self.storage, "Asgard", self.current
                    )  # type: ignore[arg-type]
        self.assertEqual(self.storage.written, [])

    def test_rejects_mismatched_version_world_or_mutable_historical_zip(self) -> None:
        """No permite restaurar metadata de otra versión, mundo o ZIP vigente mutable."""
        published = self.add_version(5)
        other_version = {**manifest(6), "filename": "worlds/Asgard/versions/6/world.zip"}
        for value in (
            other_version,
            {**published, "world": "Midgard"},
            {**published, "filename": "worlds/Midgard/versions/5/world.zip"},
            manifest(5),
        ):
            with self.subTest(value=value):
                self.storage.objects["worlds/Asgard/versions/5/manifest.json"] = value
                with self.assertRaises(RuntimeError):
                    list_previous_versions(
                        self.storage, "Asgard", self.current
                    )  # type: ignore[arg-type]
        self.assertEqual(self.storage.written, [])

    def test_reports_record_disappearing_after_listing(self) -> None:
        """Distingue un historial vacío de un registro listado que luego desapareció."""
        self.add_version(5)
        with (
            patch.object(self.storage, "get_json", return_value=None),
            self.assertRaisesRegex(RuntimeError, "no está disponible"),
        ):
            list_previous_versions(
                self.storage, "Asgard", self.current
            )  # type: ignore[arg-type]
        self.assertEqual(self.storage.written, [])

    def test_reports_invalid_json_or_encoding_without_writes(self) -> None:
        """Convierte metadata ilegible en un error de dominio sin continuar la consulta."""
        self.add_version(5)
        for error in (
            json.JSONDecodeError("invalid", "{", 0),
            UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid"),
        ):
            with self.subTest(error=type(error).__name__):
                with (
                    patch.object(self.storage, "get_json", side_effect=error),
                    self.assertRaisesRegex(RuntimeError, "No se pudo interpretar") as caught,
                ):
                    list_previous_versions(
                        self.storage, "Asgard", self.current
                    )  # type: ignore[arg-type]
                self.assertIs(caught.exception.__cause__, error)
        self.assertEqual(self.storage.written, [])

    def test_storage_errors_are_not_treated_as_missing_history(self) -> None:
        """Propaga errores de permisos y conexión tanto del listado como de la lectura."""
        self.add_version(5)
        errors = (
            ClientError({"Error": {"Code": "AccessDenied", "Message": "denied"}}, "GetObject"),
            ConnectionError("offline"),
        )
        for method in ("list_keys", "get_json"):
            for error in errors:
                with self.subTest(method=method, error=type(error).__name__):
                    with (
                        patch.object(self.storage, method, side_effect=error),
                        self.assertRaises(type(error)) as caught,
                    ):
                        list_previous_versions(
                            self.storage, "Asgard", self.current
                        )  # type: ignore[arg-type]
                    self.assertIs(caught.exception, error)
        self.assertEqual(self.storage.written, [])


if __name__ == "__main__":
    unittest.main()
