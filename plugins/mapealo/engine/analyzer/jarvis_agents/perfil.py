"""Parser de PERFIL.md de un agente — habilidades + herramientas externas."""
import re
from pathlib import Path


_HABILIDAD_ROW = re.compile(r'^\|\s*(H\d+)\s*\|\s*([^|]+?)\s*\|\s*([^|]*?)\s*\|\s*([^|]+?)\s*\|')
_TOOLS_LINE    = re.compile(r'\*\*Herramientas externas:\*\*\s*(.+)$')


def parse_perfil(perfil_path: Path) -> dict:
    """
    Lee PERFIL.md y extrae:
      - habilidades: [{id, label, trigger, accion}]
      - herramientas: [str]  (lista plana de tools externas)
    Retorna dict vacío si no existe.
    """
    if not perfil_path.is_file():
        return {}
    try:
        text = perfil_path.read_text(encoding='utf-8')
    except OSError:
        return {}

    habilidades: list = []
    herramientas: list = []
    section = None

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            heading = stripped.lstrip("#").strip().lower()
            if "batería de habilidades" in heading or "bateria de habilidades" in heading:
                section = "habilidades"
            elif "conocimiento especializado" in heading:
                section = "conocimiento"
            else:
                section = None
            continue

        if section == "habilidades":
            m = _HABILIDAD_ROW.match(line)
            if m:
                habilidades.append({
                    "id":      m.group(1),
                    "label":   m.group(2).strip(),
                    "trigger": m.group(3).strip(),
                    "accion":  m.group(4).strip(),
                })
        elif section == "conocimiento":
            m = _TOOLS_LINE.search(line)
            if m:
                herramientas = _split_tools(m.group(1))

    return {
        "habilidades":  habilidades,
        "herramientas": herramientas,
    }


def _split_tools(raw: str) -> list:
    """Divide la lista de herramientas en items individuales — separadores ',' fuera de paréntesis."""
    items, buf, depth = [], [], 0
    for ch in raw:
        if ch == '(':
            depth += 1
            buf.append(ch)
        elif ch == ')':
            depth = max(0, depth - 1)
            buf.append(ch)
        elif ch == ',' and depth == 0:
            t = "".join(buf).strip().strip('.').strip('`')
            if t:
                items.append(t)
            buf = []
        else:
            buf.append(ch)
    tail = "".join(buf).strip().strip('.').strip('`')
    if tail:
        items.append(tail)
    return items
