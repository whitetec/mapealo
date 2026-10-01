"""
Parser PHP por regex — extrae CPTs y shortcodes registrados.

CONTRATO (importante):
    Solo se reconocen llamadas cuyo PRIMER ARGUMENTO es un STRING LITERAL
    (entre comillas simples o dobles, sin interpolación ni concatenación).
    Si el primer argumento es una variable, una constante, una función o
    cualquier expresión más compleja, la llamada se IGNORA SILENCIOSAMENTE.

    Ejemplos que SÍ se detectan:
        register_post_type('book', [...])
        register_post_type("book", $args)
        add_shortcode('hello', 'render_hello')

    Ejemplos que NO se detectan (limitación deliberada del parser):
        register_post_type($slug, $args)
        register_post_type(MY_CONST, [...])
        register_post_type('prefix' . $name, [...])

Esta restricción hace el parser predecible: nunca produce falsos positivos
ni adivina, a costa de perder algunos CPTs dinámicos. Para cubrirlos bien
hay que pasar a un parser AST PHP real (out of scope para v1.4).
"""
import re
from pathlib import Path


# Coincide con: nombre_funcion ( "literal"  o  'literal'  seguido de , o )
# - Lookbehind excluye \w, > (object op `->`) y : (static `::`)
# - Lookahead exige `,` o `)` después del literal (sin operadores como `.` o `+`)
# Captura solo el primer argumento literal; el resto se ignora.
_PATTERN_TPL = r"""(?<![\w>:]){fn}\s*\(\s*(?:'([^'\\]*)'|"([^"\\]*)")\s*[,)]"""

# Funciones de interés en v1.4 — ampliable
_PATTERNS = {
    "cpts":       re.compile(_PATTERN_TPL.format(fn="register_post_type")),
    "shortcodes": re.compile(_PATTERN_TPL.format(fn="add_shortcode")),
}


def _find_in_text(text: str, pattern: re.Pattern) -> list:
    """Retorna los strings literales del primer argumento, deduplicados, ordenados."""
    seen: set = set()
    out: list = []
    for m in pattern.finditer(text):
        s = m.group(1) or m.group(2) or ""
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return sorted(out)


def parse_php_file(php: Path) -> dict:
    """Parsea un único .php. Retorna {'cpts': [...], 'shortcodes': [...]}."""
    try:
        text = php.read_text(errors='ignore')
    except OSError:
        return {"cpts": [], "shortcodes": []}
    return {key: _find_in_text(text, pat) for key, pat in _PATTERNS.items()}


def parse_php_components(root: Path) -> dict:
    """
    Recorre todos los .php bajo `root` (recursivo) y agrega los hallazgos.
    Salta dirs comunes irrelevantes (vendor, node_modules, .git).

    Retorna {'cpts': [str], 'shortcodes': [str]} ordenados y dedupeados.
    """
    skip = {"vendor", "node_modules", ".git", "tests", "test", "build", "dist"}
    agg: dict = {key: set() for key in _PATTERNS}

    for php in _walk_php(root, skip):
        result = parse_php_file(php)
        for key, items in result.items():
            agg[key].update(items)

    return {key: sorted(vals) for key, vals in agg.items()}


def _walk_php(root: Path, skip: set):
    """Generador de .php podando dirs in-place."""
    import os
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in skip and not d.startswith(".")]
        for fn in files:
            if fn.endswith(".php"):
                yield Path(dirpath) / fn
