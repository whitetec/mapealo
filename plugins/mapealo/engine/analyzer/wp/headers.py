"""
Parser de headers WordPress (en plugins y themes).

Formato (estándar WP):
    Plugin Name: Mi Plugin
    Version:     1.2.3
    Description: ...

Aparecen en el docblock al inicio de un .php (plugin) o de style.css (theme).
"""
import re

# Acepta cualquier prefijo de docblock: '/*', ' *', '/**', '//', o nada.
# El prefijo se consume hasta la primera letra mayúscula del nombre del campo.
_HEADER_LINE = re.compile(
    r'^[ \t/*]*([A-Z][A-Za-z0-9 \-]+):\s*(.+?)\s*$',
    re.MULTILINE,
)

# Campos que reconocemos (otros se ignoran)
KNOWN_FIELDS = {
    "Plugin Name", "Theme Name", "Version", "Description", "Author",
    "Author URI", "Plugin URI", "Theme URI", "Template", "Text Domain",
    "Domain Path", "Network", "Requires at least", "Requires PHP",
    "License", "License URI",
}


def parse_header(text: str) -> dict:
    """
    Extrae los campos del header WP del texto dado.
    Lee solo los primeros 8KB para evitar parsear el cuerpo entero.
    Retorna dict {campo: valor}.
    """
    head = text[:8192]
    out: dict = {}
    for m in _HEADER_LINE.finditer(head):
        key = m.group(1).strip()
        val = m.group(2).strip()
        # Si el valor termina con `*/` (cierre de docblock single-line), recortar
        if val.endswith("*/"):
            val = val[:-2].strip()
        if key in KNOWN_FIELDS and key not in out:
            out[key] = val
    return out
