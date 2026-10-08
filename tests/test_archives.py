import hashlib
import stat
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path

from bifrost.archives import create_zip, extract_zip, validate_zip, verify_zip


class ArchiveTests(unittest.TestCase):
    def test_round_trip_preserves_paths_and_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            source = root / "source"
            (source / "subdir").mkdir(parents=True)
            (source / "world.fwl2").write_bytes(b"metadata")
            (source / "subdir" / "world.db2").write_bytes(b"database")

            archive = create_zip(source, root / "world.zip")
            destination = extract_zip(archive, root / "restored")

            self.assertEqual((destination / "world.fwl2").read_bytes(), b"metadata")
            self.assertEqual((destination / "subdir" / "world.db2").read_bytes(), b"database")
            self.assertTrue(verify_zip(archive, __import__("hashlib").sha256(archive.read_bytes()).hexdigest()))

    def test_extract_rejects_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            archive = root / "unsafe.zip"
            with zipfile.ZipFile(archive, "w") as file:
                file.writestr("../escape.txt", "no")
            with self.assertRaises(ValueError):
                extract_zip(archive, root / "destination")


class ArchiveValidationTests(unittest.TestCase):
    def write_zip(
        self,
        root: Path,
        entries: list[tuple[str | zipfile.ZipInfo, bytes]],
        compression: int = zipfile.ZIP_DEFLATED,
    ) -> Path:
        """Construye un ZIP ficticio con rutas y contenido elegidos para cada escenario."""
        archive = root / "world.zip"
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(archive, "w", compression=compression) as file:
                for name, data in entries:
                    if isinstance(name, str):
                        member = zipfile.ZipInfo(name)
                        # Conserva nombres malformados que ZipInfo normaliza al crear en Windows.
                        member.filename = name
                        member.compress_type = compression
                    else:
                        member = name
                    file.writestr(member, data)
        return archive

    def assert_rejected_before_extraction(
        self, archive: Path, error_type: type[Exception] = ValueError
    ) -> None:
        """Comprueba que un rechazo no altere el ZIP ni cree archivos de destino."""
        original = archive.read_bytes()
        self.assertTrue(verify_zip(archive, hashlib.sha256(original).hexdigest()))
        with self.assertRaises(error_type):
            validate_zip(archive)
        destination = archive.parent / "destination"
        with self.assertRaises(error_type):
            extract_zip(archive, destination)
        self.assertFalse(destination.exists())
        self.assertEqual(archive.read_bytes(), original)
        self.assertEqual(list(archive.parent.iterdir()), [archive])

    def test_valid_archive_preserves_bytes_and_relative_paths(self) -> None:
        """Acepta subcarpetas, espacios y acentos sin reescribir ni extraer durante la validación."""
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            entries = [
                ("Peña del Dragón/", b""),
                ("Peña del Dragón/save.db2", b"\x00progress\xff"),
                ("Peña del Dragón/metadatos.fwl2", b"metadata"),
                ("subdir_backup_1/.bifrost-state.json", b"arbitrary world file"),
                ("vacío/", b""),
            ]
            archive = self.write_zip(root, entries)
            original = archive.read_bytes()

            validate_zip(archive)

            self.assertEqual(archive.read_bytes(), original)
            self.assertEqual(list(root.iterdir()), [archive])
            destination = extract_zip(archive, root / "destination")
            for name, data in entries:
                if name.endswith("/"):
                    self.assertTrue((destination / name).is_dir())
                else:
                    self.assertEqual((destination / name).read_bytes(), data)
            self.assertEqual(archive.read_bytes(), original)

    def test_hash_verification_accepts_match_and_rejects_mismatch(self) -> None:
        """La verificación usa los bytes originales del ZIP y no acepta otro SHA-256."""
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            archive = self.write_zip(root, [("subdir/save.db2", b"progress")])
            original = archive.read_bytes()

            validate_zip(archive)

            self.assertTrue(verify_zip(archive, hashlib.sha256(original).hexdigest()))
            self.assertFalse(verify_zip(archive, hashlib.sha256(b"other ZIP").hexdigest()))
            self.assertEqual(archive.read_bytes(), original)

    def test_rejects_unsafe_or_nonportable_paths_before_extracting_any_file(self) -> None:
        """Rechaza traversal, unidades, UNC, ADS y nombres incompatibles con Windows."""
        names = (
            "../escape.db",
            "subdir/../../escape.db",
            "subdir/../save.db",
            "/absolute.db",
            "//server/share/save.db",
            "C:/absolute.db",
            "C:relative.db",
            r"C:\absolute.db",
            r"\rooted.db",
            r"\\server\share\save.db",
            r"subdir\..\escape.db",
            r"subdir\save.db",
            "./save.db",
            "subdir//save.db",
            ".",
            "..",
            "save.db:stream",
            "subdir:/save.db",
            "CON",
            "nul.db",
            "CON .db",
            "COM9.bin",
            "LPT¹.db",
            "CONIN$.txt",
            "save.db.",
            "save.db ",
            "subdir./save.db",
            "save?.db",
            "save*.db",
            "save<.db",
            'save".db',
            "save|.db",
            "save\n.db",
            "save\t.db",
            "save\x7f.db",
            "a" * 256,
            "😀" * 128,
        )
        for name in names:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary_dir:
                archive = self.write_zip(
                    Path(temporary_dir), [("safe.db", b"valid"), (name, b"unsafe")]
                )
                self.assert_rejected_before_extraction(archive)

    def test_rejects_nul_in_original_member_name(self) -> None:
        """Detecta NUL en el nombre original aunque ZipInfo exponga filename truncado."""
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            archive = self.write_zip(root, [("nullxname.db", b"progress")])
            archive.write_bytes(
                archive.read_bytes().replace(b"nullxname.db", b"null\x00name.db")
            )
            self.assert_rejected_before_extraction(archive)

    def test_rejects_duplicates_case_collisions_and_file_directory_conflicts(self) -> None:
        """Evita que dos entradas se sobrescriban o cambien su significado al extraer en Windows."""
        for names in (
            ("same.db", "same.db"),
            ("SAVE.db", "save.db"),
            ("Saves/a.db", "saves/b.db"),
            ("Straße/a.db", "STRASSE/b.db"),
            ("subdir", "subdir/save.db"),
            ("subdir/save.db", "subdir"),
            ("subdir/", "subdir"),
            ("subdir", "subdir/"),
        ):
            with self.subTest(names=names), tempfile.TemporaryDirectory() as temporary_dir:
                archive = self.write_zip(
                    Path(temporary_dir), [(name, b"progress") for name in names]
                )
                self.assert_rejected_before_extraction(archive)

    def test_rejects_links_special_files_and_inconsistent_directory_attributes(self) -> None:
        """Rechaza entradas que declaren enlaces o tipos ajenos a archivos y carpetas."""
        kinds = (
            ("unsafe", stat.S_IFLNK),
            ("unsafe", stat.S_IFIFO),
            ("unsafe", stat.S_IFCHR),
            ("unsafe", stat.S_IFBLK),
            ("unsafe", stat.S_IFSOCK),
            ("unsafe", stat.S_IFDIR),
            ("unsafe/", stat.S_IFREG),
        )
        for name, kind in kinds:
            with self.subTest(name=name, kind=kind), tempfile.TemporaryDirectory() as temporary_dir:
                member = zipfile.ZipInfo(name)
                member.create_system = 3
                member.external_attr = (kind | 0o777) << 16
                archive = self.write_zip(
                    Path(temporary_dir), [("safe.db", b"valid"), (member, b"../outside.db")]
                )
                self.assert_rejected_before_extraction(archive)

    def test_rejects_unreadable_or_truncated_zip_before_creating_destination(self) -> None:
        """No trata bytes ajenos a ZIP ni un archivo truncado como una descarga utilizable."""
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            archive = self.write_zip(root, [("save.db", b"progress")])
            original = archive.read_bytes()
            for data in (b"not a ZIP", original[:-10]):
                with self.subTest(data=data):
                    archive.write_bytes(data)
                    self.assert_rejected_before_extraction(archive, zipfile.BadZipFile)

    def test_rejects_bad_crc_even_when_archive_sha256_matches(self) -> None:
        """Un hash externo coincidente no habilita un ZIP con contenido internamente corrupto."""
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            payload = b"unique corruption target"
            archive = self.write_zip(root, [("save.db", payload)], zipfile.ZIP_STORED)
            data = bytearray(archive.read_bytes())
            data[data.index(payload)] ^= 1
            corrupted = bytes(data)
            archive.write_bytes(corrupted)

            self.assertTrue(verify_zip(archive, hashlib.sha256(corrupted).hexdigest()))
            with self.assertRaises(zipfile.BadZipFile):
                validate_zip(archive)
            self.assertEqual(archive.read_bytes(), corrupted)
            self.assertEqual(list(root.iterdir()), [archive])

    def test_missing_archive_is_reported_without_creating_output(self) -> None:
        """Conserva la distinción entre un ZIP ausente y uno con rutas inválidas."""
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            with self.assertRaises(FileNotFoundError):
                validate_zip(root / "missing.zip")
            self.assertEqual(list(root.iterdir()), [])


if __name__ == "__main__":
    unittest.main()

