# Bifröst

Bifröst sincroniza mundos de Valheim entre jugadores mediante Cloudflare R2. Permite descargar la versión compartida antes de hostear, conservar un backup local y publicar el progreso al terminar.

Cada descarga registra la versión base local. Si otra persona publica una versión nueva antes de tu push, Bifröst bloquea la subida desactualizada para evitar que se pierda progreso.

La descarga para hostear reemplaza el mundo local de forma recuperable y adquiere su lock. La descarga de copia guarda un ZIP verificado en `.bifrost-copies` sin reemplazar mundos, adquirir locks ni modificar la versión base local.

Antes de subir, Bifröst comprueba el lock al comenzar y nuevamente antes de transferir. Un lock ajeno activo bloquea la publicación; un lock propio o la ausencia de lock permiten continuar.

## Desarrollo

Requiere Python 3.11 o posterior.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
python -m bifrost
```

Completá `.env` con la ruta local de los mundos y las credenciales de R2. Nunca confirmes ese archivo en Git.

## Pruebas

```powershell
python -m pytest
```

Las pruebas locales usan directorios temporales y no tocan mundos reales ni R2.

## Documentación

- `docs/architecture.md`: responsabilidades y dependencias internas.
- `docs/protocol.md`: claves, manifests, locks y orden de publicación.
- `docs/r2-setup.md`: variables necesarias para conectar Cloudflare R2.
