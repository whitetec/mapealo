"""
Grafo de imports internos entre módulos de una app Python.

Resuelve por **ruta de módulo**, no por nombre de archivo. Dos archivos que se
llaman igual en paquetes distintos (`analyzer/builder.py` y `analyzer/wp/builder.py`)
son dos nodos distintos y sus imports no se mezclan.

Contrato de resolución:
  - Se leen `import x` y `from x import y`, incluidos los relativos (`from . import`).
  - Un import se convierte en edge solo si apunta a un módulo de la app. Todo lo
    que no esté en el índice (stdlib, paquetes de terceros) se descarta sin lista
    de exclusión.
  - `from paquete import nombre` apunta al módulo `paquete.nombre` si existe; si
    `nombre` es una función o una clase, cae al `__init__` del paquete.
  - El alias por sufijo (`main` → `src/main.py`) solo se registra cuando es
    único. Un sufijo ambiguo se descarta: es preferible perder un edge a
    atribuirlo al módulo equivocado.
"""
import ast
from pathlib import Path


def dotted_name(rel_path: str) -> str:
    """`analyzer/wp/builder.py` → `analyzer.wp.builder`
       `analyzer/wp/__init__.py` → `analyzer.wp`"""
    parts = list(Path(rel_path).parts)
    if not parts:
        return ""
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    elif parts[-1].endswith(".py"):
        parts[-1] = parts[-1][:-3]
    return ".".join(parts)


def build_module_index(modules: list) -> tuple[dict, dict]:
    """
    modules: [{"id": str, "rel_path": str}, ...]

    Retorna (exacto, por_sufijo):
      exacto     — {'analyzer.wp.builder': id}
      por_sufijo — {'builder': id} solo para los sufijos que resuelven a un
                   único módulo. Cubre apps que agregan un dir al sys.path.
    """
    exact: dict = {}
    for m in modules:
        rel = m.get("rel_path", "")
        if not rel:
            continue
        dn = dotted_name(rel)
        if dn:
            exact[dn] = m["id"]

    # Sufijos: se descartan los que aparecen más de una vez
    suffix_hits: dict = {}
    for dn, mid in exact.items():
        parts = dn.split(".")
        for i in range(1, len(parts)):
            suffix_hits.setdefault(".".join(parts[i:]), set()).add(mid)

    by_suffix = {
        s: next(iter(ids)) for s, ids in suffix_hits.items()
        if len(ids) == 1 and s not in exact
    }
    return exact, by_suffix


def _resolve(dotted: str, exact: dict, by_suffix: dict) -> str | None:
    if not dotted:
        return None
    return exact.get(dotted) or by_suffix.get(dotted)


def _absolute_base(rel_path: str, module: str | None, level: int) -> str:
    """Convierte un `from ... import` relativo en su ruta de módulo absoluta."""
    pkg = list(Path(rel_path).parts[:-1])
    if level > 0:
        # level=1 es el paquete del archivo; cada nivel extra sube uno
        cut = len(pkg) - (level - 1)
        pkg = pkg[:cut] if cut >= 0 else []
    elif module:
        pkg = []
    base = pkg + (module.split(".") if module else [])
    return ".".join(base)


def _targets_of_file(tree: ast.AST, rel_path: str, exact: dict, by_suffix: dict) -> list:
    """Ids de módulo que este archivo importa."""
    found: list = []

    def add(mid):
        if mid and mid not in found:
            found.append(mid)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                add(_resolve(alias.name, exact, by_suffix))

        elif isinstance(node, ast.ImportFrom):
            base = _absolute_base(rel_path, node.module, node.level or 0)
            hit  = False
            # `from paquete import modulo` apunta al submódulo si existe
            for alias in node.names:
                mid = _resolve(f"{base}.{alias.name}" if base else alias.name,
                               exact, by_suffix)
                if mid:
                    add(mid)
                    hit = True
            # Si lo importado no era un módulo (una función, una clase), el
            # edge va al paquete o al archivo que la define
            if not hit:
                add(_resolve(base, exact, by_suffix))

    return found


def build_import_graph(modules: list, app_dir: Path) -> dict:
    """
    Retorna {module_id: [module_id importado, ...]} sin auto-referencias.
    Un archivo que no parsea se saltea sin romper la corrida.
    """
    exact, by_suffix = build_module_index(modules)
    graph: dict = {}

    for m in modules:
        rel = m.get("rel_path", "")
        if not rel:
            continue
        path = app_dir / rel
        try:
            tree = ast.parse(path.read_text(errors="ignore"))
        except (SyntaxError, OSError, ValueError):
            continue
        targets = [t for t in _targets_of_file(tree, rel, exact, by_suffix)
                   if t != m["id"]]
        if targets:
            graph[m["id"]] = targets

    return graph
