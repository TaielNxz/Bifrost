# Bifröst

Bifröst sincroniza mundos de Valheim entre jugadores mediante Cloudflare R2. Permite descargar la versión compartida antes de hostear, conservar un backup local y publicar el progreso al terminar.

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
