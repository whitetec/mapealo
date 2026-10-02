"""Detecta el stack y la estructura de un proyecto."""
import ast
import os
import re
from pathlib import Path


STACK_SIGNATURES = {
    "python-flask":   ["flask"],
    "python-fastapi": ["fastapi"],
    "python-django":  ["django"],
    "python":         [],
}

# Directorio → pilar (señal fuerte, se evalúa antes que los keywords)
DIR_PILLAR_MAP = {
    "gui":        "interfaz",
    "ui":         "interfaz",
    "interface":  "interfaz",
    "frontend":   "interfaz",
    "views":      "interfaz",
    "windows":    "interfaz",
    "widgets":    "interfaz",
    "scripts":    "herramientas",
    "tools":      "herramientas",
    "bin":        "herramientas",
    "cli":        "herramientas",
    "api":        "servicios",
    "routes":     "servicios",
    "endpoints":  "servicios",
    "handlers":   "servicios",
    "models":     "backbone",
    "db":         "backbone",
    "database":   "backbone",
    "migrations": "backbone",
    "adapters":   "integradores",
    "clients":    "integradores",
    "connectors": "integradores",
}

PILLAR_HINTS = {
    "backbone": ["auth", "login", "password", "user", "role", "db", "database",
                 "model", "config", "settings", "scheduler", "alert", "mailer",
                 "mail", "base", "core", "admin", "panel", "utils", "helper",
                 "organiz", "pipeline", "manager"],
    "servicios": ["backup", "sync", "storage", "report", "service", "activo",
                  "inventario", "riesgo", "risk", "incident", "factur",
                  "batch", "ingest", "worker"],
    "integradores": ["agent", "agente", "integr", "veeam", "rclone", "notif",
                     "webhook", "client", "extern", "sftp", "smtp",
                     "export", "wp_"],
    "micuenta": ["perfil", "profile", "account", "cuenta", "soporte", "support",
                 "billing", "seguridad", "security"],
    "procesamiento": ["image", "imag", "ocr", "preprocess", "layout", "portada",
                      "detect", "tiff", "deskew", "vision", "photo", "media",
                      "encoder", "decoder", "resiz", "compress"],
}

PILLAR_META = {
    "backbone":      {"label": "Backbone",      "color": "#1f6feb", "glow": "#388bfd", "desc": "Infraestructura técnica transversal."},
    "servicios":     {"label": "Servicios",     "color": "#238636", "glow": "#2ea043", "desc": "Servicios de valor para el usuario."},
    "integradores":  {"label": "Integradores",  "color": "#9e6a03", "glow": "#d29922", "desc": "Adaptadores con sistemas externos."},
    "micuenta":      {"label": "Mi Cuenta",     "color": "#6e40c9", "glow": "#8957e5", "desc": "Portal de autogestión del usuario."},
    "interfaz":      {"label": "Interfaz",      "color": "#bf4b8a", "glow": "#db61a2", "desc": "Componentes de interfaz de usuario."},
    "herramientas":  {"label": "Herramientas",  "color": "#4a7c7e", "glow": "#56a3a6", "desc": "Scripts y utilidades de soporte."},
    "procesamiento": {"label": "Procesamiento", "color": "#e36209", "glow": "#f0883e", "desc": "Procesamiento de datos e imágenes."},
}


def detect_stack(app_dir: Path) -> str:
    req = app_dir / "requirements.txt"
    if req.exists():
        txt = req.read_text().lower()
        for stack, kws in STACK_SIGNATURES.items():
            if kws and any(kw in txt for kw in kws):
                return stack
    if list(app_dir.rglob("*.py")):
        return "python"
    if list(app_dir.rglob("*.js")) or list(app_dir.rglob("*.ts")):
        return "node"
    return "unknown"


def assign_pillar(module_id: str, rel_path: str = "") -> str:
    """Asigna pilar: primero por directorio padre, luego por keywords del nombre."""
    from pathlib import Path as _Path
    parts = [p.lower() for p in _Path(rel_path).parts[:-1]] if rel_path else []
    for part in parts:
        if part in DIR_PILLAR_MAP:
            return DIR_PILLAR_MAP[part]
    name = module_id.lower()
    for pillar, hints in PILLAR_HINTS.items():
        if any(h in name for h in hints):
            return pillar
    return "backbone"


_SKIP_DIRS = {"test", "tests", "migration", "migrations", "__pycache__",
              "venv", ".venv", "env", "node_modules", ".mapealo", ".jarvis-map",
              ".git", ".tox", "dist", "build", ".mypy_cache", ".pytest_cache"}


def _init_tiene_contenido(path: Path) -> bool:
    """Un `__init__.py` cuenta como módulo solo si define algo propio.

    Los vacíos o de solo re-exports son plomería del paquete y ensucian el mapa;
    uno con funciones (`analyzer/__init__.py` define `detect_kind`) es un módulo
    real y sin él quedan sueltos los imports que le apuntan.
    """
    try:
        tree = ast.parse(path.read_text(errors="ignore"))
    except (SyntaxError, OSError, ValueError):
        return False
    return any(
        isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Assign))
        for n in tree.body
    )


def find_python_modules(app_dir: Path) -> list:
    """Recorre con os.walk podando dirs antes de descender (no rglob completo)."""
    files: list = []
    for root, dirs, fnames in os.walk(app_dir):
        # poda in-place: evita descender en dirs irrelevantes
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith(".")]
        for fn in fnames:
            if not fn.endswith(".py"):
                continue
            if fn.startswith("test_") or fn.endswith("_test.py"):
                continue
            if fn == "__init__.py" and not _init_tiene_contenido(Path(root) / fn):
                continue
            files.append(Path(root) / fn)
    return sorted(files)


def _const_value(node: ast.AST) -> str:
    """Extrae el valor string de un nodo Constant sin usar eval."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return ""


def _detect_factory_calls(app_dir: Path, factory_name: str, *, use_first_arg_as_id: bool) -> list:
    """
    Encuentra asignaciones `var = FactoryName(...)` en todos los .py.
    Si use_first_arg_as_id, intenta usar el primer arg string como id;
    en su defecto usa el nombre de la variable.
    """
    found   = []
    pattern = re.compile(rf"{re.escape(factory_name)}\s*\(")
    for pyfile in app_dir.rglob("*.py"):
        src = pyfile.read_text(errors='ignore')
        if not pattern.search(src):
            continue
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
                continue
            func  = node.value.func
            fname = getattr(func, 'id', None) or getattr(func, 'attr', None)
            if fname != factory_name:
                continue
            id_from_arg = ""
            if use_first_arg_as_id and node.value.args:
                id_from_arg = _const_value(node.value.args[0])
            for t in node.targets:
                if isinstance(t, ast.Name):
                    found.append({
                        "id":   id_from_arg or t.id,
                        "var":  t.id,
                        "file": str(pyfile.relative_to(app_dir)),
                    })
    return found


def detect_flask_blueprints(app_dir: Path) -> list:
    return _detect_factory_calls(app_dir, "Blueprint", use_first_arg_as_id=True)


def detect_fastapi_routers(app_dir: Path) -> list:
    return _detect_factory_calls(app_dir, "APIRouter", use_first_arg_as_id=False)
