"""Análisis básico de un módulo Python: fn / models / routes / vars."""
import ast
from pathlib import Path


_ROUTE_DECORATORS = {
    "route", "get", "post", "put", "patch", "delete", "head", "options",
}

_MODEL_BASES = {"Model", "Base", "db.Model", "BaseModel", "SQLModel"}


_FUNC_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)


def _args_str(node: ast.FunctionDef) -> str:
    args = [a.arg for a in node.args.args if a.arg != "self"]
    return ", ".join(args)


def _first_docline(node) -> str:
    doc = ast.get_docstring(node) or ""
    return doc.split("\n")[0][:90] if doc else ""


def _decorator_owner(dec) -> str:
    """El objeto sobre el que se declara la ruta: `router`, `admin_bp`, `app`.

    Es lo que después permite saber bajo qué prefijo está montada. Sin esto,
    dos blueprints definidos en el mismo archivo son indistinguibles.
    """
    func = getattr(dec, "func", None)
    if isinstance(func, ast.Attribute):
        try:
            return ast.unparse(func.value)
        except Exception:
            return ""
    return ""


def _decorator_route(dec) -> str | None:
    """Extrae método y path de un decorador de ruta Flask/FastAPI."""
    if isinstance(dec, ast.Call):
        func  = dec.func
        fname = getattr(func, 'attr', None) or getattr(func, 'id', None)
        if fname not in _ROUTE_DECORATORS:
            return None
        # None = el decorador no declara path (no es una ruta que sepamos leer).
        # "" sí es una ruta: con un router montado en /admin, `get("")` ES /admin,
        # o sea la portada de la sección. Descartarlo por falsy perdía justo esas.
        path = None
        if dec.args and isinstance(dec.args[0], ast.Constant) \
                and isinstance(dec.args[0].value, str):
            path = dec.args[0].value
        for kw in dec.keywords:
            if kw.arg == "path" and isinstance(kw.value, ast.Constant) \
                    and isinstance(kw.value.value, str):
                path = kw.value.value
        if path is None:
            return None
        method = fname.upper() if fname != "route" else "GET"
        if fname == "route":
            for kw in dec.keywords:
                if kw.arg == "methods" and isinstance(kw.value, ast.List):
                    methods = [e.value for e in kw.value.elts if isinstance(e, ast.Constant)]
                    method = "|".join(methods)
        return f"{method} {path or '/'}"
    return None


def analyze_file(pyfile: Path, app_dir: Path) -> dict:
    src = pyfile.read_text(errors='ignore')
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return {"fn": [], "models": [], "routes": [], "vars": [], "tags": []}

    result: dict = {"fn": [], "models": [], "routes": [], "vars": [],
                    "endpoints": [], "tags": ["activo"]}

    for node in ast.walk(tree):
        # Funciones (no privadas). `async def` es AsyncFunctionDef, que NO
        # hereda de FunctionDef: mirando solo FunctionDef, una app FastAPI
        # async quedaba sin funciones y sin una sola ruta.
        if isinstance(node, _FUNC_NODES) and not node.name.startswith("__"):
            # Rutas primero
            route_found = False
            for dec in node.decorator_list:
                r = _decorator_route(dec)
                if r:
                    doc    = _first_docline(node)
                    method, _, path = r.partition(" ")
                    result["routes"].append([r, doc])
                    result["endpoints"].append({
                        "method": method,
                        "path":   path,
                        "owner":  _decorator_owner(dec),
                        "fn":     node.name,
                        "doc":    doc,
                    })
                    route_found = True
            if not route_found and not node.name.startswith("_"):
                sig = f"{node.name}({_args_str(node)})"
                doc = _first_docline(node)
                result["fn"].append([sig, doc])

        # Clases — modelos SQLAlchemy / Pydantic / SQLModel
        elif isinstance(node, ast.ClassDef):
            bases = {
                getattr(b, 'id', None) or
                (getattr(b, 'attr', None) if isinstance(b, ast.Attribute) else None)
                for b in node.bases
            }
            if bases & _MODEL_BASES:
                fields = _extract_columns(node)
                result["models"].append([node.name, ", ".join(fields)])

    # Constantes de nivel módulo (ALL_CAPS)
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id.isupper() and len(t.id) > 1:
                    val = _simple_value(node.value)
                    result["vars"].append([t.id, val])

    return result


def _extract_columns(cls_node: ast.ClassDef) -> list:
    """Extrae nombres de columnas/campos de un modelo."""
    fields = []
    for node in cls_node.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and not t.id.startswith("_"):
                    fields.append(t.id)
        elif isinstance(node, (ast.AnnAssign,)):
            if isinstance(node.target, ast.Name) and not node.target.id.startswith("_"):
                fields.append(node.target.id)
    return fields[:8]


def _simple_value(node: ast.AST) -> str:
    if isinstance(node, ast.Constant):
        v = str(node.value)
        return v[:60] if len(v) > 60 else v
    if isinstance(node, ast.Name):
        return node.id
    return ""
