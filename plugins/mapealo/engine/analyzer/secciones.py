"""
Espacio de URLs de una app web, armado como árbol de secciones.

Una ruta declarada en el código es relativa al prefijo bajo el que se monta su
blueprint o su router. `@admin_bp.route("/clients/new")` no es `/clients/new`:
es `/admin/clients/new`, y el `/admin` vive en el archivo que la registra, no
en el que la declara. Sin resolver eso el árbol sale plausible y equivocado.

Reglas de resolución:

- Flask: `Blueprint(..., url_prefix=)` en el constructor, y
  `register_blueprint(bp, url_prefix=)` en el registro. El registro **pisa** al
  constructor, que es lo que hace Flask.
- FastAPI: `APIRouter(prefix=)` en el constructor, y `include_router(r, prefix=)`
  en el registro. Acá se **concatenan**: registro primero, constructor después.
- El nombre usado en el registro se resuelve contra los imports de ese archivo
  (`from .admin import bp as admin_bp`, `from . import admin` + `admin.router`).
  No se hace matching por parecido de nombres.

Un owner del que no se encuentra registro alguno NO se monta en la raíz: sus
rutas quedan en una sección marcada como sin resolver. Si no, una falla de
resolución se ve idéntica a un blueprint montado en la raíz y no se detecta
nunca.
"""
import ast
from pathlib import Path, PurePosixPath

from .imports import _absolute_base, build_module_index

SIN_RESOLVER = "?"
RAIZ = "/"

_CTOR_FLASK   = "Blueprint"
_CTOR_FASTAPI = "APIRouter"
_REGISTROS = {
    "register_blueprint": "url_prefix",
    "include_router":     "prefix",
}


def _const_str(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _kw_str(call, nombre):
    for k in call.keywords:
        if k.arg == nombre:
            return _const_str(k.value)
    return None


def _arboles(app_dir: Path, modules: list) -> dict:
    """{module_id: (rel_path, ast)} de los módulos que parsean."""
    out = {}
    for m in modules:
        rel = m.get("rel_path", "")
        if not rel:
            continue
        try:
            out[m["id"]] = (rel, ast.parse((app_dir / rel).read_text(errors="ignore")))
        except (OSError, SyntaxError, ValueError):
            continue
    return out


def _constructores(arboles: dict) -> dict:
    """{(module_id, owner): {'kind': 'flask'|'fastapi', 'prefix': str}}"""
    out = {}
    for mid, (_rel, tree) in arboles.items():
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
                continue
            call  = node.value
            fname = getattr(call.func, "id", None) or getattr(call.func, "attr", None)
            if fname == _CTOR_FLASK:
                kind, pref = "flask", _kw_str(call, "url_prefix") or ""
            elif fname == _CTOR_FASTAPI:
                kind, pref = "fastapi", _kw_str(call, "prefix") or ""
            else:
                continue
            for t in node.targets:
                if isinstance(t, ast.Name):
                    out[(mid, t.id)] = {"kind": kind, "prefix": pref}
    return out


def _mapa_imports(rel_path: str, tree: ast.AST, exact: dict, by_suffix: dict) -> dict:
    """
    {nombre_local: (module_id, nombre_en_ese_modulo | None)}

    `None` significa que el nombre local es el módulo entero (`from . import admin`),
    así que el owner se toma del atributo (`admin.router` → owner `router`).
    """
    mapa = {}
    resolver = lambda d: exact.get(d) or by_suffix.get(d)

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            base = _absolute_base(rel_path, node.module, node.level or 0)
            for a in node.names:
                local = a.asname or a.name
                # `from paquete import modulo`
                mid_sub = resolver(f"{base}.{a.name}" if base else a.name)
                if mid_sub:
                    mapa[local] = (mid_sub, None)
                    continue
                # `from modulo import nombre`
                mid = resolver(base)
                if mid:
                    mapa[local] = (mid, a.name)
        elif isinstance(node, ast.Import):
            for a in node.names:
                local = a.asname or a.name.split(".")[0]
                mid   = resolver(a.name if a.asname else a.name.split(".")[0])
                if mid:
                    mapa[local] = (mid, None)
    return mapa


def _destino(arg: ast.AST, mid_actual: str, mapa: dict) -> tuple | None:
    """El (module_id, owner) al que apunta el primer argumento del registro."""
    if isinstance(arg, ast.Name):
        destino = mapa.get(arg.id)
        if destino and destino[1]:
            return (destino[0], destino[1])
        if destino and destino[1] is None:
            return None          # es un módulo, no un blueprint
        return (mid_actual, arg.id)          # definido en este mismo archivo
    if isinstance(arg, ast.Attribute) and isinstance(arg.value, ast.Name):
        destino = mapa.get(arg.value.id)
        if destino:
            return (destino[0], arg.attr)
        return None
    return None


def _mapas_por_modulo(arboles: dict, modules: list) -> dict:
    exact, by_suffix = build_module_index(modules)
    return {mid: _mapa_imports(rel, tree, exact, by_suffix)
            for mid, (rel, tree) in arboles.items()}


def _duenio_real(mid: str, owner: str, mapa: dict) -> tuple:
    """
    Dónde vive realmente el blueprint sobre el que se declaró la ruta.

    `app/assets.py` decora con `@cybersec_bp.route(...)`, pero ese blueprint se
    define en `app/cybersec.py`. Buscando el constructor en el módulo que
    declara la ruta no aparece nunca.
    """
    destino = mapa.get(owner)
    if destino and destino[1]:
        return (destino[0], destino[1])
    return (mid, owner)


def _registros(arboles: dict, mapas: dict) -> dict:
    """{(module_id, owner): prefijo_del_registro}"""
    out = {}
    for mid, (rel, tree) in arboles.items():
        mapa = mapas.get(mid, {})
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fname = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            if fname not in _REGISTROS or not node.args:
                continue
            destino = _destino(node.args[0], mid, mapa)
            if destino:
                out[destino] = _kw_str(node, _REGISTROS[fname]) or ""
    return out


def _unir(*partes) -> str:
    """Une tramos de URL sin duplicar barras. Devuelve siempre algo con `/`."""
    limpio = [p.strip("/") for p in partes if p and p.strip("/")]
    return "/" + "/".join(limpio) if limpio else "/"


def resolver_urls(app_dir: Path, modules: list, detail: dict) -> list:
    """
    [{url, method, module_id, fn, doc, resuelto}] con la URL completa de cada
    endpoint. `resuelto` es False cuando no se encontró dónde se monta.
    """
    arboles = _arboles(app_dir, modules)
    mapas   = _mapas_por_modulo(arboles, modules)
    ctors   = _constructores(arboles)
    regs    = _registros(arboles, mapas)

    salida = []
    for m in modules:
        mid = m["id"]
        for ep in (detail.get(mid) or {}).get("endpoints", []):
            owner = ep.get("owner", "")
            clave = _duenio_real(mid, owner, mapas.get(mid, {}))
            ctor  = ctors.get(clave)
            reg   = regs.get(clave)

            if ctor is None and reg is None:
                # `@app.route(...)` sobre la app directa: la ruta ya es absoluta
                resuelto, prefijo = owner in ("app", ""), ""
            elif reg is None:
                resuelto, prefijo = False, ""
            elif ctor and ctor["kind"] == "flask":
                # En Flask el url_prefix del registro pisa al del constructor
                resuelto, prefijo = True, reg or ctor["prefix"]
            elif ctor:
                resuelto, prefijo = True, _unir(reg, ctor["prefix"])
            else:
                resuelto, prefijo = True, reg

            salida.append({
                "url":       _unir(prefijo, ep["path"]) if resuelto else ep["path"],
                "method":    ep["method"],
                "module_id": mid,
                "rel_path":  m.get("rel_path", ""),
                "fn":        ep.get("fn", ""),
                "doc":       ep.get("doc", ""),
                "resuelto":  resuelto,
            })
    return salida


def _tramos(url: str, resuelto: bool) -> list:
    partes = [p for p in PurePosixPath(url).parts if p != "/"]
    return partes if resuelto else [SIN_RESOLVER, *partes]


def build_secciones(app_dir: Path, modules: list, detail: dict) -> dict:
    """
    Árbol de secciones en la misma forma genérica que consume la vista de
    contención: `{groups, children}`.

    Un grupo es un tramo de la URL. Una hoja es un endpoint, y lleva el archivo
    y la función que lo atiende, así que un clic referencia el rango exacto.
    """
    urls = resolver_urls(app_dir, modules, detail)
    if not urls:
        return {}

    groups = {RAIZ: {"id": RAIZ, "label": "/", "parent": None, "depth": 0}}

    def _asegurar(tramos, sin_resolver):
        """Crea la cadena de grupos y devuelve el id del más profundo."""
        padre, acc = RAIZ, []
        for depth, parte in enumerate(tramos, start=1):
            acc.append(parte)
            gid = RAIZ + "/".join(acc)
            if gid not in groups:
                groups[gid] = {"id": gid, "label": parte, "parent": padre,
                               "depth": depth, "sin_resolver": sin_resolver}
            padre = gid
        return padre

    # Primera pasada: los grupos salen del tramo padre de cada URL, así que una
    # hoja no crea una caja propia. `/admin/usuarios/crear` crea /admin y
    # /admin/usuarios, no /admin/usuarios/crear.
    for u in urls:
        tramos = _tramos(u["url"], u["resuelto"])
        _asegurar(tramos[:-1], not u["resuelto"])

    # Segunda pasada: si la URL completa ES una sección, el endpoint es su
    # portada y va adentro de esa caja, no al lado.
    children, vistos = [], set()
    for u in urls:
        tramos  = _tramos(u["url"], u["resuelto"])
        gid_uno = RAIZ + "/".join(tramos)
        if tramos and gid_uno in groups:
            grupo, etiqueta = gid_uno, f"{u['method']} /"
        else:
            grupo    = _asegurar(tramos[:-1], not u["resuelto"])
            etiqueta = f"{u['method']} {tramos[-1]}" if tramos else f"{u['method']} /"

        nid = f"{u['method']} {u['url']}@{u['module_id']}"
        if nid in vistos:
            continue
        vistos.add(nid)
        children.append({
            "id":       nid,
            # El id de la hoja es único por endpoint, pero /api/enviar necesita
            # el nodo del graph para resolver la ruta del archivo.
            "node_id":  u["module_id"],
            "label":    etiqueta,
            "group":    grupo,
            "url":      u["url"],
            "fn":       u["fn"],
            "desc":     u["doc"] or f"{u['method']} {u['url']}",
            "rel_path": u["rel_path"],
            "tags":     [] if u["resuelto"] else ["sin resolver"],
        })

    from .builder import _GROUP_COLORS
    top = sorted(g["id"] for g in groups.values() if g["depth"] == 1)
    for i, gid in enumerate(top):
        groups[gid]["color"] = _GROUP_COLORS[i % len(_GROUP_COLORS)]

    return {"groups": list(groups.values()), "children": children}
