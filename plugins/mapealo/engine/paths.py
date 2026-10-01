"""Resolución portable de las raíces de proyectos mapeables.

jarvis-map nació asumiendo `~/jarvis-apps/apps/<app_id>`. Para que el tool
corra en una máquina ajena, esa raíz se descubre en vez de asumirse. Orden de
precedencia, de más explícito a más heurístico:

  1. `JARVIS_MAP_APPS_DIR`  — lista separada por `os.pathsep`
  2. `~/.config/jarvis-map/config.json` → `apps_dirs: []`
  3. autodetección sobre nombres de raíz frecuentes bajo el home
  4. el workspace propio del tool (`~/.local/share/jarvis-map/apps`)

Un `app_id` que además sea una ruta existente (absoluta, relativa o con `~`)
se usa tal cual: es el camino portable cuando no hay ninguna raíz reconocible.
"""
import json
import os
import re
from pathlib import Path

ENV_ROOTS = "JARVIS_MAP_APPS_DIR"


def user_config() -> Path:
    """Config de usuario. Función y no constante: resolverla al importar la
    congela contra el `HOME` del momento."""
    base = os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")
    return Path(base) / "jarvis-map/config.json"

# Raíces de desarrollo frecuentes, relativas al home, en orden de preferencia.
_CANDIDATE_ROOTS = [
    "jarvis-apps/apps",     # convención Jarvis (la del autor)
    "proyectos", "Proyectos", "projects", "Projects",
    "dev", "src", "code", "repos", "work", "workspace",
    "Documentos/proyectos", "Documents/projects",
]

# Marcadores de que un directorio es un proyecto y no una carpeta cualquiera.
_PROJECT_MARKERS = (
    ".git", "CLAUDE.md", "package.json", "requirements.txt",
    "pyproject.toml", "setup.py", "wp-config.php", "go.mod", "Cargo.toml",
)

APP_ID_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$')

# Nombres que nunca son apps mapeables.
SKIP_NAMES = {"node_modules", "__pycache__", ".git", ".venv", "venv", "dist", "build"}


def workspace_root() -> Path:
    """Raíz escribible propia del tool. Aloja stubs que el tool mismo genera
    (por ejemplo el del ecosistema de agentes autodetectado)."""
    return Path(
        os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local/share")
    ) / "jarvis-map/apps"


def _from_env() -> list[Path]:
    raw = os.environ.get(ENV_ROOTS, "").strip()
    if not raw:
        return []
    return [Path(p).expanduser() for p in raw.split(os.pathsep) if p.strip()]


def _from_user_config() -> list[Path]:
    try:
        cfg = json.loads(user_config().read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return []
    dirs = cfg.get("apps_dirs") or []
    if isinstance(dirs, str):
        dirs = [dirs]
    return [Path(str(p)).expanduser() for p in dirs]


def _looks_like_project(d: Path) -> bool:
    if not d.is_dir() or d.name in SKIP_NAMES or d.name.startswith('_'):
        return False
    return any((d / m).exists() for m in _PROJECT_MARKERS)


def _autodetect() -> list[Path]:
    """Raíces candidatas que existen y contienen al menos un proyecto real.

    Solo mira una lista acotada de nombres: recorrer el home entero es lento
    (y en un home cifrado, muy lento) y produce falsos positivos.
    """
    home  = Path.home()
    found = []
    for rel in _CANDIDATE_ROOTS:
        d = home / rel
        if not d.is_dir():
            continue
        try:
            if any(_looks_like_project(c) for c in d.iterdir()):
                found.append(d)
        except OSError:
            continue
    return found


def apps_roots() -> list[Path]:
    """Raíces donde buscar apps, sin duplicados y preservando el orden."""
    roots: list[Path] = []
    for src in (_from_env(), _from_user_config(), _autodetect(), [workspace_root()]):
        for p in src:
            if p.is_dir() and p not in roots:
                roots.append(p)
    return roots


def is_app_id(raw: str) -> bool:
    """True si `raw` tiene forma de id (no de ruta)."""
    return bool(APP_ID_RE.match(raw or "")) and not raw.startswith('_')


def _as_path(raw: str) -> Path | None:
    """Interpreta `raw` como ruta a un proyecto. None si no lo es."""
    if not raw:
        return None
    # Un id puro nunca se trata como ruta relativa, salvo que exista como dir
    # en el cwd: `mapealo anubis` desde un home con un dir `anubis` suelto
    # debe seguir resolviendo por raíces, no por cwd.
    looks_like_path = (
        os.sep in raw or raw.startswith('~') or raw in ('.', '..')
        or raw.startswith('./') or raw.startswith('../')
    )
    if not looks_like_path:
        return None
    p = Path(raw).expanduser()
    try:
        p = p.resolve()
    except (OSError, RuntimeError):
        return None
    return p if p.is_dir() else None


def resolve_app_dir(app_id: str) -> Path | None:
    """Devuelve el directorio del proyecto, o None si no se encontró.

    No resolvemos el path final a propósito: romper symlinks legítimos
    (`orus -> /media/op/Container/orus`) cambiaría el `.jarvis-map/` de lugar.
    """
    direct = _as_path(app_id)
    if direct is not None:
        return direct
    if not is_app_id(app_id):
        return None
    for root in apps_roots():
        candidate = root / app_id
        if candidate.is_dir():
            return candidate
    return None


def app_id_for(raw: str) -> str:
    """Id canónico para `raw`, que puede venir como id o como ruta."""
    direct = _as_path(raw)
    return direct.name if direct is not None else raw


def list_apps() -> list[tuple[str, Path]]:
    """(id, dir) de todas las apps visibles. El primer root gana ante choque."""
    seen: dict[str, Path] = {}
    for root in apps_roots():
        try:
            children = sorted(root.iterdir())
        except OSError:
            continue
        for d in children:
            if not d.is_dir() or d.name.startswith('_') or d.name in SKIP_NAMES:
                continue
            seen.setdefault(d.name, d)
    return list(seen.items())


def claude_home() -> Path:
    """Directorio de configuración de Claude Code."""
    raw = os.environ.get("CLAUDE_CONFIG_DIR", "").strip()
    return Path(raw).expanduser() if raw else Path.home() / ".claude"


def allowed_open_roots() -> list[Path]:
    """Roots donde `/api/open` puede abrir archivos.

    Derivado, no hardcodeado: el home de Claude, las raíces de apps y los
    directorios del home que tienen `CLAUDE.md` (cada agente es uno).
    """
    roots = [claude_home()] + apps_roots()
    home  = Path.home()
    try:
        for d in sorted(home.iterdir()):
            if d.is_dir() and (d / "CLAUDE.md").is_file():
                roots.append(d)
    except OSError:
        pass
    out: list[Path] = []
    for p in roots:
        if p not in out:
            out.append(p)
    return out
