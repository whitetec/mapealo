"""Detección del kind de fuente y dispatch — interfaz pública del paquete."""
import json
from pathlib import Path


KIND_PYTHON           = "python"
KIND_WORDPRESS        = "wordpress"
KIND_WORDPRESS_REMOTE = "wordpress-remote"
KIND_JARVIS_AGENTS    = "jarvis-agents"
KIND_NEXTJS           = "nextjs"
KIND_UNKNOWN          = "unknown"

VALID_KINDS = {KIND_PYTHON, KIND_WORDPRESS, KIND_WORDPRESS_REMOTE, KIND_JARVIS_AGENTS, KIND_NEXTJS}

CONFIG_FILE = "jarvis-map.json"


def load_config(app_dir: Path) -> dict:
    """
    Lee `<app>/jarvis-map.json` si existe. Es la fuente autoritativa para
    `kind`, credenciales SSH y paths PHP locales adicionales.

    Schema esperado (todos los campos opcionales salvo `kind`):
        {
          "kind": "wordpress-remote",
          "ssh": {
            "host":    "1.2.3.4",
            "user":    "mcp-agent",
            "key":     "~/.ssh/keyname",   // path absoluto o ~ expandible
            "port":    22,                  // opcional, default 22
            "wp_path": "/home/.../site/"    // path remoto del WP install
          },
          "local_php_dirs": ["mu-plugins"]  // dirs relativos a app_dir a parsear
        }
    """
    cfg_file = app_dir / CONFIG_FILE
    if not cfg_file.exists():
        return {}
    try:
        return json.loads(cfg_file.read_text(encoding='utf-8'))
    except (json.JSONDecodeError, OSError):
        return {}


def detect_kind(app_dir: Path) -> str:
    """
    Devuelve el kind de la fuente.

    Prioridad:
      1. `jarvis-map.json` → `kind` (autoritativo)
      2. Marcadores WordPress local: wp-config.php, wp-content/
      3. Next.js: package.json con `next` en la app o en un subdirectorio de
         primer nivel (va antes que Python: una app Next suele traer scripts .py
         sueltos y el mapa quedaba con solo esos scripts)
      4. Marcadores Python: requirements.txt, pyproject.toml, setup.py, *.py
      4. Marcador WordPress por header de tema en style.css
      5. unknown
    """
    cfg = load_config(app_dir)
    if cfg.get("kind") in VALID_KINDS:
        return cfg["kind"]

    if (app_dir / "wp-config.php").exists():
        return KIND_WORDPRESS
    if (app_dir / "wp-content").is_dir():
        return KIND_WORDPRESS

    from .nextjs import encontrar_raiz
    if encontrar_raiz(app_dir) is not None:
        return KIND_NEXTJS

    if (app_dir / "requirements.txt").exists():
        return KIND_PYTHON
    if (app_dir / "pyproject.toml").exists():
        return KIND_PYTHON
    if (app_dir / "setup.py").exists():
        return KIND_PYTHON

    if any(app_dir.rglob("*.py")):
        return KIND_PYTHON
    for css in app_dir.rglob("style.css"):
        try:
            if "Theme Name:" in css.read_text(errors='ignore')[:512]:
                return KIND_WORDPRESS
        except OSError:
            continue
    return KIND_UNKNOWN
