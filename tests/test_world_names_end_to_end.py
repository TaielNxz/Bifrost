import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

from botocore.exceptions import ClientError

from bifrost.archives import create_zip
from bifrost.cli import copy_menu, lock_menu, pull_menu, push_menu, status_menu
from bifrost.config import Settings
from bifrost.local_state import STATE_FILENAME, read_base_version, save_base_version
from bifrost.local_worlds import COPIES_DIRECTORY_NAME, list_worlds
from bifrost.manifests import build_manifest
from bifrost.paths import current_zip_key, manifest_key, state_key, version_manifest_key, version_zip_key
from bifrost.remote_state import read_world_state
from bifrost.storage import R2Storage


class MemoryS3Client:
    """Simula objetos, paginación y precondiciones S3 sin construir conexiones remotas."""

    def __init__(self):
        """Inicializa objetos en memoria y registros de lecturas, descargas y mutaciones."""
        self.objects = {}
        self.etags = {}
        self.reads = []
        self.downloads = []
        self.mutations = []
        self.counter = 0

    def seed(self, key, body):
        """Prepara un objeto ficticio y su ETag sin registrarlo como una operación de la CLI."""
        self.counter += 1
        self.objects[key] = body
        self.etags[key] = f'"etag-{self.counter}"'
        return self.etags[key]

    def seed_json(self, key, value):
        """Prepara metadata ficticia serializada como la que leería el adaptador S3."""
        self.seed(key, json.dumps(value, ensure_ascii=False).encode("utf-8"))

    def get_paginator(self, operation):
        """Entrega el paginador falso para las consultas de objetos."""
        assert operation == "list_objects_v2"
        return self

    def paginate(self, *, Bucket, Prefix, Delimiter=None):
        """Lista objetos o prefijos en páginas de dos entradas para ejercitar el listado completo."""
        keys = sorted(key for key in self.objects if key.startswith(Prefix))
        if Delimiter is not None:
            prefixes = sorted({
                Prefix + key[len(Prefix):].split(Delimiter)[0] + Delimiter
                for key in keys if Delimiter in key[len(Prefix):]
            })
            entries = [{"Prefix": prefix} for prefix in prefixes]
            field = "CommonPrefixes"
        else:
            entries = [{"Key": key} for key in keys]
            field = "Contents"
        for start in range(0, len(entries), 2):
            yield {field: entries[start:start + 2]}

    def get_object(self, *, Bucket, Key):
        """Lee bytes con su ETag o reproduce el error S3 de un objeto inexistente."""
        self.reads.append(Key)
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        return {"Body": io.BytesIO(self.objects[Key]), "ETag": self.etags[Key]}

    def put_object(self, *, Bucket, Key, Body, ContentType, IfMatch=None, IfNoneMatch=None):
        """Aplica precondiciones y registra el JSON únicamente cuando la escritura es aceptada."""
        if (
            IfMatch is not None and self.etags.get(Key) != IfMatch
            or IfNoneMatch == "*" and Key in self.objects
        ):
            raise ClientError({"Error": {"Code": "PreconditionFailed"}}, "PutObject")
        etag = self.seed(Key, Body)
        self.mutations.append(("json", Key))
        return {"ETag": etag}

    def upload_fileobj(self, file, bucket, key):
        """Guarda el ZIP leído del archivo local y registra su subida."""
        self.seed(key, file.read())
        self.mutations.append(("zip", key))

    def download_fileobj(self, bucket, key, file):
        """Descarga exclusivamente los bytes del objeto solicitado al archivo temporal."""
        self.downloads.append(key)
        file.write(self.objects[key])

    def copy_object(self, *, Bucket, CopySource, Key):
        """Copia un ZIP heredado a su ubicación histórica y registra el efecto."""
        self.seed(Key, self.objects[CopySource["Key"]])
        self.mutations.append(("copy", Key))

    def delete_object(self, *, Bucket, Key):
        """Elimina el objeto indicado y registra la eliminación."""
        self.objects.pop(Key, None)
        self.etags.pop(Key, None)
        self.mutations.append(("delete", Key))


class WorldNamesEndToEndTests(unittest.TestCase):
    def settings(self, root):
        """Construye configuración ficticia que se usará únicamente con el cliente en memoria."""
        return Settings("https://example.invalid", "test-id", "test-secret", "test-bucket", root, "Jugador")

    def action(self, menu, root, storage):
        """Ejecuta una selección y sus confirmaciones, capturando la salida de la CLI."""
        output = io.StringIO()
        with redirect_stdout(output), patch("builtins.input", side_effect=["1", "s", "s"]):
            menu(self.settings(root), storage)
        return output.getvalue()

    def test_accented_name_survives_push_copy_host_and_republication(self):
        """Recorre la sesión completa conservando nombres, archivos, base, backup y orden de publicación."""
        name = "Peña del Dragón"
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            first = root / "first-player"
            second = root / "second-player"
            first.mkdir()
            second.mkdir()
            world = first / name
            (world / "datos del mundo").mkdir(parents=True)
            (world / "save.db").write_bytes(b"initial progress")
            (world / "datos del mundo" / "árbol.bin").write_bytes(b"nested data")
            client = MemoryS3Client()
            storage = R2Storage(self.settings(first), client=client)

            # Los mundos inválidos y un conflicto entre páginas no deben impedir la sesión válida.
            for blocked in ("Asgard", "asgard", "NUL"):
                client.seed_json(f"worlds/{blocked}/state.json", {})
            client.seed_json("worlds/Valhalla/state.json", {
                "schema_version": 1, "revision": 1, "lock": None,
                "manifest": {"world": "Otro", "version": 1, "filename": current_zip_key("Otro")},
            })
            excluded_objects = dict(client.objects)

            self.assertIn("subido", self.action(push_menu, first, storage))
            initial = read_world_state(storage, name).value["manifest"]
            self.assertEqual(initial["world"], name)
            self.assertTrue(initial["filename"].startswith(f"worlds/{name}/versions/1/"))
            self.assertEqual(client.mutations[:2], [("zip", initial["filename"]), ("json", state_key(name))])
            self.assertEqual(read_base_version(first, name)["sha256"], initial["sha256"])
            with ZipFile(io.BytesIO(client.objects[initial["filename"]])) as archive:
                self.assertEqual(set(archive.namelist()), {"save.db", "datos del mundo/árbol.bin"})

            # Una copia conserva tanto el progreso activo como su registro de base y el estado remoto.
            local = second / name
            local.mkdir()
            (local / "save.db").write_bytes(b"old local progress")
            os.utime(local, (1_577_836_800, 1_577_836_800))
            save_base_version(second, name, 1, "f" * 64)
            base_before = (second / STATE_FILENAME).read_bytes()
            remote_before = dict(client.objects)
            mutations_before = list(client.mutations)
            self.assertIn("Copia verificada", self.action(copy_menu, second, storage))
            copies = list((second / COPIES_DIRECTORY_NAME).glob("*.zip"))
            self.assertEqual([copy.name for copy in copies], [f"{name}_v1_{initial['sha256'][:12]}.zip"])
            self.assertEqual(copies[0].read_bytes(), client.objects[initial["filename"]])
            self.assertEqual((local / "save.db").read_bytes(), b"old local progress")
            self.assertEqual((second / STATE_FILENAME).read_bytes(), base_before)
            self.assertEqual(client.objects, remote_before)
            self.assertEqual(client.mutations, mutations_before)

            # Hostear reemplaza solo este mundo, conserva su backup y vincula la base al lock adquirido.
            self.assertIn("descargado y verificado", self.action(pull_menu, second, storage))
            self.assertEqual((local / "save.db").read_bytes(), b"initial progress")
            self.assertEqual((local / "datos del mundo" / "árbol.bin").read_bytes(), b"nested data")
            backups = list(second.glob(f"{name}_pre_pull_*"))
            self.assertEqual(len(backups), 1)
            self.assertEqual((backups[0] / "save.db").read_bytes(), b"old local progress")
            hosted = read_world_state(storage, name).value
            base = read_base_version(second, name)
            self.assertEqual(base["session_id"], hosted["lock"]["session_id"])
            self.assertEqual(base["sha256"], initial["sha256"])

            # Publicar el progreso conserva la identidad y completa el ZIP antes de liberar el lock.
            (local / "save.db").write_bytes(b"new hosted progress")
            offset = len(client.mutations)
            self.assertIn("subido", self.action(push_menu, second, storage))
            published = read_world_state(storage, name).value
            latest = published["manifest"]
            self.assertEqual(latest["world"], name)
            self.assertEqual(latest["version"], 2)
            self.assertIsNone(published["lock"])
            self.assertNotEqual(initial["filename"], latest["filename"])
            self.assertEqual(client.mutations[offset:offset + 2], [("zip", latest["filename"]), ("json", state_key(name))])
            self.assertEqual(read_base_version(second, name), {"version": 2, "sha256": latest["sha256"]})
            with ZipFile(io.BytesIO(client.objects[latest["filename"]])) as archive:
                self.assertEqual(archive.read("save.db"), b"new hosted progress")
            self.assertEqual([item.name for item in list_worlds(second)], [name])
            for key, body in excluded_objects.items():
                self.assertEqual(client.objects[key], body)
            self.assertFalse(any(key.startswith(("worlds/NUL/", "worlds/Asgard/", "worlds/asgard/")) for key in client.reads))

    def test_legacy_zip_locations_remain_usable_with_accented_names(self):
        """Descarga y publica desde las dos ubicaciones heredadas sin alterar el nombre ni perder el ZIP previo."""
        name = "Ásgard del Sur"
        for filename in (current_zip_key(name), version_zip_key(name, 4)):
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as temporary_dir:
                root = Path(temporary_dir)
                source = root / "source"
                source.mkdir()
                (source / "save.db").write_bytes(b"legacy progress")
                archive = create_zip(source, root / "legacy.zip")
                metadata = build_manifest(archive, name, 4, "Jugador", filename=filename)
                worlds = root / "worlds"
                worlds.mkdir()
                client = MemoryS3Client()
                client.seed(filename, archive.read_bytes())
                client.seed_json(manifest_key(name), metadata)
                storage = R2Storage(self.settings(worlds), client=client)
                self.assertTrue(read_world_state(storage, name).legacy)

                self.assertIn("descargado y verificado", self.action(pull_menu, worlds, storage))
                self.assertEqual(client.downloads, [filename])
                self.assertEqual((worlds / name / "save.db").read_bytes(), b"legacy progress")
                self.assertFalse(read_world_state(storage, name).legacy)
                (worlds / name / "save.db").write_bytes(b"new progress")
                self.assertIn("subido", self.action(push_menu, worlds, storage))
                published = read_world_state(storage, name).value
                self.assertEqual(published["manifest"]["version"], 5)
                self.assertEqual(published["manifest"]["world"], name)
                self.assertIsNone(published["lock"])
                historical = storage.get_json(version_manifest_key(name, 4))
                self.assertEqual(historical["filename"], version_zip_key(name, 4))
                self.assertEqual(client.objects[historical["filename"]], archive.read_bytes())

    def test_rejected_remote_names_do_not_read_download_or_modify_objects(self):
        """Comprueba el bloqueo con la CLI y el adaptador S3 reales cuando no queda ningún mundo utilizable."""
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            client = MemoryS3Client()
            for name in ("Asgard", "asgard", "NUL", "Mundo.", "..", ""):
                client.seed_json(f"worlds/{name}/state.json", {})
            storage = R2Storage(self.settings(root), client=client)
            before = dict(client.objects)
            for menu in (status_menu, pull_menu, copy_menu, lock_menu):
                output = io.StringIO()
                with redirect_stdout(output), patch("builtins.input") as user_input:
                    if menu is status_menu:
                        menu(storage)
                    else:
                        menu(self.settings(root), storage)
                user_input.assert_not_called()
                self.assertIn("[BLOQUEADO]", output.getvalue())
                self.assertIn("'Asgard', 'asgard'", output.getvalue())
            self.assertEqual(client.reads, [])
            self.assertEqual(client.downloads, [])
            self.assertEqual(client.mutations, [])
            self.assertEqual(client.objects, before)
            self.assertEqual(list(root.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
