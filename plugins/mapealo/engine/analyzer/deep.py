"""Análisis profundo: call graph, FK de modelos, deps externas, tests."""
import ast
import re
from pathlib import Path


_THIRD_PARTY_SKIP = {
    "flask", "fastapi", "sqlalchemy", "os", "sys", "re", "json", "datetime",
    "pathlib", "typing", "collections", "functools", "itertools", "abc",
    "dataclasses", "logging", "hashlib", "hmac", "base64", "uuid", "time",
    "threading", "subprocess", "shutil", "tempfile", "io", "string", "math",
    "random", "copy", "enum", "contextlib", "traceback", "inspect",
}


def build_call_graph(pyfiles: list, module_map: dict) -> dict:
    """
    Construye grafo de llamadas inter-módulo.
    module_map: {stem: module_id}
    Retorna: {module_id: [module_id_llamado, ...]}
    """
    calls = {mid: [] for mid in module_map.values()}

    for pyfile in pyfiles:
        stem = pyfile.stem
        caller = module_map.get(stem)
        if not caller:
            continue
        try:
            tree = ast.parse(pyfile.read_text(errors='ignore'))
        except SyntaxError:
            continue

        imported_froms = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                top = node.module.split(".")[-1]
                callee = module_map.get(top)
                if callee and callee != caller:
                    imported_froms[top] = callee

        for callee in sorted(set(imported_froms.values())):
            if callee not in calls[caller]:
                calls[caller].append(callee)

    return {k: v for k, v in calls.items() if v}


def extract_model_relationships(pyfiles: list) -> dict:
    """
    Detecta relationship() y ForeignKey() en modelos SQLAlchemy.
    Retorna: {ModelName: [{field, related_model, type}]}
    """
    rels = {}
    fk_pattern  = re.compile(r'ForeignKey\s*\(\s*["\']([^"\']+)["\']')
    rel_pattern = re.compile(r'relationship\s*\(\s*["\']([^"\']+)["\']')

    for pyfile in pyfiles:
        src = pyfile.read_text(errors='ignore')
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue

        for cls in ast.walk(tree):
            if not isinstance(cls, ast.ClassDef):
                continue
            cls_src_lines = src.split("\n")[cls.lineno - 1: cls.end_lineno]
            cls_src = "\n".join(cls_src_lines)

            fks  = fk_pattern.findall(cls_src)
            rls  = rel_pattern.findall(cls_src)

            if fks or rls:
                rels[cls.name] = {
                    "foreign_keys":  [fk.split(".")[0] for fk in fks],
                    "relationships": rls,
                }

    return rels


def extract_external_deps(app_dir: Path) -> list:
    """Lee requirements.txt y filtra paquetes notables."""
    req = app_dir / "requirements.txt"
    if not req.exists():
        return []
    deps = []
    for line in req.read_text().splitlines():
        line = re.sub(r'[>=<!].+', '', line.strip()).strip()
        if line and not line.startswith("#"):
            deps.append(line.lower())
    return deps


def find_test_coverage(app_dir: Path, module_map: dict) -> dict:
    """Mapea archivos de test a los módulos que cubren."""
    coverage = {}
    test_files = list(app_dir.rglob("test_*.py")) + list(app_dir.rglob("*_test.py"))
    for tf in test_files:
        stem = re.sub(r'^test_|_test$', '', tf.stem)
        target = module_map.get(stem)
        if target:
            coverage.setdefault(target, []).append(tf.name)
    return coverage


def detect_env_vars_project(app_dir: Path) -> list:
    """Detecta todas las variables de entorno usadas en el proyecto."""
    pattern = re.compile(r'os\.(?:getenv|environ\.get|environ\[)\s*["\']([^"\']+)["\']')
    found = set()
    for pyfile in app_dir.rglob("*.py"):
        src = pyfile.read_text(errors='ignore')
        found.update(pattern.findall(src))
    return sorted(found)
