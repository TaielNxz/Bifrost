import tempfile
import unittest
from pathlib import Path

from bifrost.manifests import build_manifest, next_version, parse_iso_datetime, validate_manifest


class ManifestTests(unittest.TestCase):
    def test_builds_manifest_and_increments_version(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            archive = Path(temporary_dir) / "world.zip"
            archive.write_bytes(b"world")
            manifest = build_manifest(archive, "Asgard", 1, "Taiel")
            self.assertEqual(manifest["world"], "Asgard")
            self.assertEqual(manifest["version"], 1)
            self.assertEqual(manifest["size"], 5)
            self.assertEqual(next_version(None), 1)
            self.assertEqual(next_version(manifest), 2)
            self.assertIsNotNone(parse_iso_datetime(manifest["uploaded_at"]).tzinfo)


class ManifestValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        """Prepara metadata válida sin credenciales ni archivos reales."""
        self.manifest = {
            "version": 5,
            "world": "Asgard",
            "filename": "worlds/Asgard/versions/5/upload-id/world.zip",
            "size": 100,
            "sha256": "a" * 64,
            "uploaded_by": "Taiel",
            "uploaded_at": "2026-09-30T22:15:00Z",
        }

    def test_accepts_existing_zip_layouts_and_utc_dates(self) -> None:
        """Admite las claves heredadas y versionadas que usa el protocolo."""
        for filename in (
            "worlds/Asgard/current/world.zip",
            "worlds/Asgard/versions/5/world.zip",
            "worlds/Asgard/versions/5/upload-id/world.zip",
        ):
            for date in ("2026-09-30T22:15:00Z", "2026-09-30T22:15:00+00:00"):
                with self.subTest(filename=filename, date=date):
                    value = {**self.manifest, "filename": filename, "uploaded_at": date}
                    self.assertEqual(validate_manifest("Asgard", value), value)

    def test_normalizes_hash_without_mutating_metadata(self) -> None:
        """Normaliza una copia y conserva los campos adicionales del registro."""
        value = {**self.manifest, "sha256": "A" * 64, "extra": "compatible"}
        result = validate_manifest("Asgard", value)

        self.assertEqual(result["sha256"], "a" * 64)
        self.assertEqual(result["extra"], "compatible")
        self.assertEqual(value["sha256"], "A" * 64)
        self.assertIsNot(result, value)

    def test_rejects_missing_required_fields(self) -> None:
        """No admite registros incompletos como publicaciones válidas."""
        for field in self.manifest:
            with self.subTest(field=field):
                value = {key: item for key, item in self.manifest.items() if key != field}
                with self.assertRaises(RuntimeError):
                    validate_manifest("Asgard", value)

    def test_rejects_non_object_metadata(self) -> None:
        """Rechaza JSON con tipos que no representan un manifest."""
        for value in (None, [], "manifest", 5, True):
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                validate_manifest("Asgard", value)

    def test_rejects_invalid_version_and_size(self) -> None:
        """Distingue enteros válidos de booleanos y otros tipos numéricos."""
        for field, values in (
            ("version", (True, False, 0, -1, 5.0, "5", None)),
            ("size", (True, False, -1, 100.0, "100", None)),
        ):
            for value in values:
                with self.subTest(field=field, value=value), self.assertRaises(RuntimeError):
                    validate_manifest("Asgard", {**self.manifest, field: value})

    def test_rejects_metadata_for_another_world(self) -> None:
        """Impide usar un registro que no identifica el mundo solicitado."""
        for world in ("Midgard", "", None, 5):
            with self.subTest(world=world), self.assertRaises(RuntimeError):
                validate_manifest("Asgard", {**self.manifest, "world": world})

    def test_rejects_zip_keys_outside_the_world_version(self) -> None:
        """Rechaza claves de otro mundo, versión o estructura ajena al protocolo."""
        for filename in (
            None,
            5,
            "",
            "/worlds/Asgard/versions/5/world.zip",
            "worlds/Midgard/versions/5/world.zip",
            "worlds/Asgard/versions/6/world.zip",
            "worlds/Asgard/versions/05/world.zip",
            "worlds/Asgard/current/other.zip",
            "worlds/Asgard/versions/5/../world.zip",
            "worlds/Asgard/versions/5/./world.zip",
            "worlds/Asgard/versions/5//world.zip",
            "worlds/Asgard/versions/5/id/subdir/world.zip",
            "worlds/Asgard/versions/5/id\\subdir/world.zip",
            "worlds/Asgard/versions/5/id\n/world.zip",
            "worlds/Asgard/versions/5/world.zip/extra",
        ):
            with self.subTest(filename=filename), self.assertRaises(RuntimeError):
                validate_manifest("Asgard", {**self.manifest, "filename": filename})

    def test_rejects_invalid_hashes(self) -> None:
        """Exige un SHA-256 hexadecimal completo para la verificación posterior."""
        for sha256 in (None, 5, "", "a" * 63, "a" * 65, "g" * 64, "a" * 64 + "\n"):
            with self.subTest(sha256=sha256), self.assertRaises(RuntimeError):
                validate_manifest("Asgard", {**self.manifest, "sha256": sha256})

    def test_rejects_missing_or_empty_authors(self) -> None:
        """Impide presentar una autoría ausente o ilegible."""
        for author in (None, 5, "", " \t"):
            with self.subTest(author=author), self.assertRaises(RuntimeError):
                validate_manifest("Asgard", {**self.manifest, "uploaded_by": author})

    def test_rejects_invalid_or_non_utc_dates(self) -> None:
        """Rechaza fechas sin zona horaria y datos que no pueden interpretarse en UTC."""
        for date in (
            None,
            5,
            "",
            "fecha inválida",
            "2026-02-30T22:15:00Z",
            "2026-09-30",
            "2026-09-30T22:15:00",
            "2026-09-30T22:15:00-03:00",
        ):
            with self.subTest(date=date), self.assertRaises(RuntimeError):
                validate_manifest("Asgard", {**self.manifest, "uploaded_at": date})


if __name__ == "__main__":
    unittest.main()

