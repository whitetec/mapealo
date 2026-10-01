"""Helpers comunes para los tests de analyzers."""
import os
import sys
import tempfile
from pathlib import Path

# Asegurar import del paquete de jarvis-map
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def write_app(files: dict[str, str]) -> Path:
    """Crea un dir temporal con los archivos dados (rel_path → contenido)."""
    tmp = Path(tempfile.mkdtemp(prefix="jmap-fx-"))
    for rel, content in files.items():
        p = tmp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return tmp
