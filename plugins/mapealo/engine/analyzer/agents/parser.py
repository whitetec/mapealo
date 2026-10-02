"""Parser de fichas de agente — agentes/<slug>.md."""
import re
from pathlib import Path


_TABLE_ROW = re.compile(r'^\|\s*([^|]+?)\s*\|\s*(.+?)\s*\|\s*$')
_DECISION  = re.compile(r'^\s*-\s+(.+)$')
_SUBAGENT_ROW = re.compile(r'^\|\s*([a-z][a-z0-9_-]+)\s*\|\s*(.+?)\s*\|\s*$', re.IGNORECASE)


# Mapeo de campos de la tabla principal → claves normalizadas en el dict de salida.
_FIELD_MAP = {
    "Tipo":         "tipo_raw",
    "Especialidad": "especialidad",
    "Objeto":       "objeto",
    "Capability":   "capability",
    "Autonomy":     "autonomy",
    "Directorio":   "directorio",
    "Módulos":      "modules_path",
    "PERFIL.md":    "perfil_path",
    "Creado":       "creado",
    "Destinatario": "destinatario",
}


def parse_fichas(agentes_dir: Path) -> list:
    """Lee todos los .md de agentes_dir y retorna lista de fichas parseadas."""
    if not agentes_dir.is_dir():
        return []
    fichas = []
    for md in sorted(agentes_dir.glob("*.md")):
        f = parse_ficha(md)
        if f:
            fichas.append(f)
    return fichas


def parse_ficha(path: Path) -> dict | None:
    """Parsea una ficha individual."""
    try:
        text = path.read_text(encoding='utf-8')
    except OSError:
        return None

    f: dict = {
        "slug":         path.stem,
        "rel_path":     str(path),
        "tipo":         "",
        "tipo_raw":     "",
        "decisiones":   [],
        "subagentes":   [],
    }

    section = "_header"
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("##"):
            section = _section_key(stripped)
            continue

        if section == "_header":
            m = _TABLE_ROW.match(line)
            if m:
                key, val = m.group(1).strip(), m.group(2).strip()
                if key in _FIELD_MAP:
                    f[_FIELD_MAP[key]] = val

        elif section == "decisiones":
            m = _DECISION.match(line)
            if m:
                f["decisiones"].append(m.group(1).strip())

        elif section == "subagentes":
            m = _SUBAGENT_ROW.match(line)
            if m and m.group(1).lower() not in ("slug", "---", ":---"):
                slug, esp = m.group(1).strip(), m.group(2).strip()
                if not slug.startswith("-"):
                    f["subagentes"].append({"slug": slug, "especialidad": esp})

    f["tipo"] = _normalize_tipo(f.get("tipo_raw", ""))
    return f


def _section_key(heading: str) -> str:
    h = heading.lstrip("#").strip().lower()
    if "decisi" in h:
        return "decisiones"
    if "sub-agent" in h or "subagent" in h:
        return "subagentes"
    return h


def _normalize_tipo(raw: str) -> str:
    """`META - Meta-agente` -> `META`. Siempre devuelve uno de META/T/AE/C, o ''.

    Tolerante al separador: guion ASCII, en-dash, em-dash o ninguno.
    Toma el primer token alfanumerico, sea cual sea el separador que lo siga.
    """
    if not raw:
        return ""
    m = re.match(r"\W*(\w+)", raw, re.UNICODE)
    if not m:
        return ""
    token = m.group(1).upper()
    if token in ("META", "T", "AE", "C"):
        return token
    return ""
