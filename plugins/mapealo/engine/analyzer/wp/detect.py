"""Detecta plugins y themes en una instalación WordPress."""
from pathlib import Path

from analyzer.wp.headers import parse_header


def _wp_content(app_dir: Path) -> Path:
    return app_dir / "wp-content"


def detect_plugins(app_dir: Path) -> list:
    """
    Cada subdirectorio de wp-content/plugins/ es un plugin.
    Plugins single-file no se soportan en v1.4 (raros y obsoletos).

    Retorna [{"slug", "dir", "rel_path", "main_file", "meta"}].
    """
    out: list = []
    plugins_dir = _wp_content(app_dir) / "plugins"
    if not plugins_dir.is_dir():
        return out

    for d in sorted(plugins_dir.iterdir()):
        if not d.is_dir() or d.name.startswith("."):
            continue
        main = _find_main_plugin_file(d)
        if not main:
            continue
        try:
            meta = parse_header(main.read_text(errors='ignore'))
        except OSError:
            meta = {}
        if "Plugin Name" not in meta:
            continue
        out.append({
            "slug":      d.name,
            "dir":       d,
            "rel_path":  str(d.relative_to(app_dir)),
            "main_file": str(main.relative_to(app_dir)),
            "meta":      meta,
        })
    return out


def detect_themes(app_dir: Path) -> list:
    """
    Cada subdirectorio de wp-content/themes/ con un style.css válido
    (header `Theme Name:`) es un theme. `Template:` indica child theme.

    Retorna [{"slug", "dir", "rel_path", "meta"}].
    """
    out: list = []
    themes_dir = _wp_content(app_dir) / "themes"
    if not themes_dir.is_dir():
        return out

    for d in sorted(themes_dir.iterdir()):
        if not d.is_dir() or d.name.startswith("."):
            continue
        css = d / "style.css"
        if not css.exists():
            continue
        try:
            meta = parse_header(css.read_text(errors='ignore'))
        except OSError:
            meta = {}
        if "Theme Name" not in meta:
            continue
        out.append({
            "slug":     d.name,
            "dir":      d,
            "rel_path": str(d.relative_to(app_dir)),
            "meta":     meta,
        })
    return out


def _find_main_plugin_file(plugin_dir: Path) -> Path | None:
    """
    Busca el .php con header `Plugin Name:` en la raíz del directorio.
    Por convención WP: archivo del mismo nombre que el dir, o el primero
    que matchee. No descendemos a subdirs (slow + spurious).
    """
    candidates = []
    same_name = plugin_dir / f"{plugin_dir.name}.php"
    if same_name.exists():
        candidates.append(same_name)
    for php in plugin_dir.glob("*.php"):
        if php != same_name:
            candidates.append(php)
    for php in candidates:
        try:
            head = php.read_text(errors='ignore')[:8192]
        except OSError:
            continue
        if "Plugin Name:" in head:
            return php
    return None
