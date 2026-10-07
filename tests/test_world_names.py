import unittest
from pathlib import Path

from bifrost.world_names import InvalidWorldNameError, validate_world_name, world_name_key


class WorldNameTests(unittest.TestCase):
    def assert_rejected(self, name: object, reason_fragment: str) -> None:
        """Comprueba que el rechazo identifique el valor original y explique el motivo."""
        with self.assertRaises(InvalidWorldNameError) as caught:
            validate_world_name(name)
        error = caught.exception
        self.assertEqual(error.name, name)
        self.assertIn(reason_fragment, error.reason)
        self.assertIn(repr(name), str(error))
        self.assertIn(error.reason, str(error))

    def test_preserves_valid_names(self) -> None:
        for name in (
            "Asgard", "Mi mundo", "Peña del Dragón", "Bifröst", "ÁSGARD",
            "Mundo.v2", ".Asgard", "Asgard..v2", "..Asgard", "Mundo_1-2",
            "Mundo (copia)", "世界", "A\u0301sgard", "COM10", "LPT10",
            "CONquista", "NULidad.txt", "Asgard.backup", "Asgard_pre_pull",
        ):
            with self.subTest(name=name):
                self.assertEqual(validate_world_name(name), name)

    def test_rejects_non_strings(self) -> None:
        for name in (None, 1, True, b"Asgard", ["Asgard"], {"world": "Asgard"}, Path("Asgard")):
            with self.subTest(name=name):
                self.assert_rejected(name, "cadena de texto")

    def test_rejects_empty_name(self) -> None:
        self.assert_rejected("", "vacío")

    def test_rejects_directory_references(self) -> None:
        for name in (".", ".."):
            with self.subTest(name=name):
                self.assert_rejected(name, "directorio actual o padre")

    def test_rejects_absolute_and_drive_relative_paths(self) -> None:
        for name in (
            "/Asgard", r"C:\Asgard", "C:/Asgard", "C:Asgard", "C:",
            r"\Asgard", r"\\server\share\Asgard", r"\\?\C:\Asgard", r"\\.\CON",
        ):
            with self.subTest(name=name):
                self.assert_rejected(name, "no una ruta")

    def test_rejects_separators_and_parent_traversal(self) -> None:
        for name in ("Asgard/copia", r"Asgard\copia", "../Asgard", r"..\Asgard", "a/../b"):
            with self.subTest(name=name):
                self.assert_rejected(name, "separadores")

    def test_rejects_windows_forbidden_characters(self) -> None:
        for character in '<>:"|?*':
            with self.subTest(character=character):
                self.assert_rejected(f"As{character}gard", "prohibido por Windows")

    def test_rejects_unicode_control_characters(self) -> None:
        # Incluye NUL, controles ASCII, DEL y controles C1, sin crear carpetas reales.
        for codepoint in (*range(32), *range(127, 160)):
            with self.subTest(codepoint=codepoint):
                self.assert_rejected(f"As{chr(codepoint)}gard", "caracteres de control")

    def test_control_characters_are_escaped_in_error_message(self) -> None:
        name = "Asgard\n\x1b[31m"
        with self.assertRaises(InvalidWorldNameError) as caught:
            validate_world_name(name)
        self.assertIn(repr(name), str(caught.exception))
        self.assertNotIn("\n", str(caught.exception))
        self.assertNotIn("\x1b", str(caught.exception))

    def test_rejects_trailing_periods_and_spaces(self) -> None:
        for name in ("Asgard.", "Asgard ", "Asgard. ", "Asgard .", " ", "   "):
            with self.subTest(name=name):
                self.assert_rejected(name, "terminar en punto o espacio")

    def test_rejects_windows_device_names_with_or_without_extensions(self) -> None:
        devices = ["CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"]
        devices += [f"{prefix}{digit}" for prefix in ("COM", "LPT") for digit in "123456789¹²³"]
        for device in devices:
            for name in (device, device.lower(), f"{device}.db", f"{device}.tar.gz", f"{device} .db"):
                with self.subTest(name=name):
                    self.assert_rejected(name, "reservado por Windows")

    def test_rejects_bifrost_internal_names(self) -> None:
        for name in (".bifrost-copies", ".BIFROST-COPIES", ".bifrost-state.json", ".Bifrost-State.JSON"):
            with self.subTest(name=name):
                self.assert_rejected(name, "reservado para archivos o carpetas de Bifröst")

    def test_rejects_bifrost_backup_markers(self) -> None:
        for name in ("Asgard_backup_1", "Asgard_pre_pull_20260101", "Asgard_BACKUP_1", "Asgard_PRE_PULL_1"):
            with self.subTest(name=name):
                self.assert_rejected(name, "reservado para backups de Bifröst")

    def test_comparison_key_ignores_case_including_accents(self) -> None:
        self.assertEqual(world_name_key("Asgard"), world_name_key("ASGARD"))
        self.assertEqual(world_name_key("Peña del Dragón"), world_name_key("PEÑA DEL DRAGÓN"))
        # casefold aplica un criterio conservador también a equivalencias como ß/SS.
        self.assertEqual(world_name_key("Straße"), world_name_key("STRASSE"))

    def test_comparison_key_preserves_accents_spaces_and_unicode_form(self) -> None:
        for first, second in (
            ("Peña", "Pena"), ("Mi mundo", "Mimundo"),
            ("Ásgard", "A\u0301sgard"), ("Asgard.v2", "Asgardv2"),
        ):
            with self.subTest(first=first, second=second):
                self.assertNotEqual(world_name_key(first), world_name_key(second))

    def test_comparison_key_rejects_invalid_names(self) -> None:
        for name in ("", "../Asgard", "NUL.txt", "Asgard ", None):
            with self.subTest(name=name):
                with self.assertRaises(InvalidWorldNameError):
                    world_name_key(name)


if __name__ == "__main__":
    unittest.main()
