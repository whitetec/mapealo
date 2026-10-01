"""
Analizador de apps Next.js (App Router, TypeScript o JavaScript).

No hay un parser de TS en Python sin dependencias, así que se trabaja con
expresiones regulares sobre el código fuente. Alcanza para lo que el mapa
necesita: qué archivos hay, qué exporta cada uno, qué rutas atiende y de quién
depende. Los rangos de líneas no se guardan: los resuelve `puente.py` contra el
archivo en disco en el momento del clic.

Raíz del proyecto: el directorio con un `package.json` que declara `next`. Puede
ser la app misma o un subdirectorio (whitetec-web tiene el sitio en `sitio/`).
Se mapean `src/` (o `app/`, `components/`, `lib/` en la raíz si no hay `src/`) y
`prisma/`. Quedan afuera `node_modules`, `.next`, los clientes generados y los
`.d.ts`.
"""
import json
import re
from pathlib import Path, PurePosixPath

from .builder import build_graph, build_dep_edges_from_calls, _GROUP_COLORS

EXTS = (".ts", ".tsx", ".js", ".jsx", ".mjs")
EXCLUIR = {"node_modules", ".next", "generated", "dist", "build", "out", ".turbo", "coverage"}
METODOS_HTTP = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS")


# ---------------------------------------------------------------- detección --

def _tiene_next(pkg: Path) -> bool:
    try:
        data = json.loads(pkg.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
    return "next" in deps


def encontrar_raiz(app_dir: Path) -> Path | None:
    """La app misma o un subdirectorio de primer nivel con un package.json de Next."""
    if (app_dir / "package.json").exists() and _tiene_next(app_dir / "package.json"):
        return app_dir
    for sub in sorted(p for p in app_dir.iterdir() if p.is_dir() and p.name not in EXCLUIR and not p.name.startswith(".")):
        pkg = sub / "package.json"
        if pkg.exists() and _tiene_next(pkg):
            return sub
    return None


def _version_next(raiz: Path) -> str:
    try:
        data = json.loads((raiz / "package.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    v = {**data.get("dependencies", {}), **data.get("devDependencies", {})}.get("next", "")
    return v.lstrip("^~")


# ----------------------------------------------------------------- archivos --

def _base_codigo(raiz: Path) -> Path:
    """`src/` si existe; si no, la raíz del proyecto."""
    return raiz / "src" if (raiz / "src").is_dir() else raiz


def _excluido(rel: PurePosixPath) -> bool:
    return any(p in EXCLUIR or (p.startswith(".") and p not in (".", "..")) for p in rel.parts)


def encontrar_archivos(raiz: Path) -> list[Path]:
    base = _base_codigo(raiz)
    candidatos: list[Path] = []
    dirs = [base] if base != raiz else [raiz / d for d in ("app", "pages", "components", "lib", "hooks", "utils") if (raiz / d).is_dir()]
    if (raiz / "prisma").is_dir():
        dirs.append(raiz / "prisma")
    for d in dirs:
        for f in d.rglob("*"):
            if not f.is_file() or f.suffix not in EXTS or f.name.endswith(".d.ts"):
                continue
            if _excluido(PurePosixPath(f.relative_to(raiz).as_posix())):
                continue
            candidatos.append(f)
    # middleware / instrumentation en la base
    for nombre in ("middleware", "instrumentation"):
        for ext in EXTS:
            f = base / f"{nombre}{ext}"
            if f.exists() and f not in candidatos:
                candidatos.append(f)
    return sorted(set(candidatos))


def ruta_corta(f: Path, raiz: Path) -> str:
    """Ruta que se muestra y agrupa: relativa al proyecto, sin el `src/` inicial."""
    rel = f.relative_to(raiz).as_posix()
    return rel[4:] if rel.startswith("src/") else rel


# ------------------------------------------------------------------- rutas --

def _url_de(corta: str) -> str | None:
    """`app/atalaya/prisma/page.tsx` → `/atalaya/prisma`. None si no es ruta."""
    p = PurePosixPath(corta)
    if not p.parts or p.parts[0] != "app":
        return None
    tramos = []
    for t in p.parts[1:-1]:
        if t.startswith("(") and t.endswith(")"):   # grupo de rutas: no suma a la URL
            continue
        if t.startswith("@"):                        # slot paralelo
            continue
        tramos.append(t)
    return "/" + "/".join(tramos)


def tipo_de_archivo(corta: str) -> str:
    nombre = PurePosixPath(corta).stem
    if corta.startswith("app/"):
        if nombre in ("page", "route", "layout", "loading", "error", "not-found", "template", "default"):
            return nombre
        if nombre in ("sitemap", "robots", "manifest", "opengraph-image", "icon", "apple-icon"):
            return "metadata"
    return "modulo"


# ---------------------------------------------------------------- análisis --

_RE_FUNC = re.compile(r"^\s*export\s+(default\s+)?(async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)?\s*(?:<[^>]*>)?\s*\(([^)]*)\)?", re.M)
_RE_CONST_FN = re.compile(r"^\s*export\s+const\s+([A-Za-z_$][\w$]*)\s*(?::[^=]+)?=\s*(async\s+)?(?:\(([^)]*)\)|([A-Za-z_$][\w$]*))\s*(?::[^=]+?)?=>", re.M)
_RE_CONST = re.compile(r"^\s*export\s+const\s+([A-Za-z_$][\w$]*)\s*(?::[^=]+)?=\s*(.{0,60})", re.M)
_RE_TIPO = re.compile(r"^\s*export\s+(?:type|interface|enum)\s+([A-Za-z_$][\w$]*)", re.M)
_RE_DEFAULT_ID = re.compile(r"^\s*export\s+default\s+([A-Za-z_$][\w$]*)\s*;?\s*$", re.M)
_RE_USE_CLIENT = re.compile(r"""^\s*["']use client["']""", re.M)
_RE_USE_SERVER = re.compile(r"""^\s*["']use server["']""", re.M)


def _doc_previa(src: str, pos: int) -> str:
    """Primera línea del comentario inmediatamente anterior a la declaración."""
    # Los regex empiezan con `^\s*`, que en modo multilínea también come el salto
    # de línea anterior: se mide desde la palabra `export`, no desde el match.
    k = src.find("export", pos)
    if k != -1:
        pos = k
    antes = src[:pos].rstrip()
    if antes.endswith("*/"):
        ini = antes.rfind("/*")
        bloque = antes[ini + 2:-2] if ini != -1 else ""
    else:
        lineas = []
        for linea in reversed(antes.splitlines()):
            t = linea.strip()
            if not t.startswith("//"):
                break
            lineas.append(t)
        bloque = "\n".join(reversed(lineas))
    for linea in bloque.splitlines():
        t = linea.strip().lstrip("/*").strip()
        if t:
            return t[:140]
    return ""


def _args(txt: str | None) -> str:
    if not txt:
        return ""
    return re.sub(r"\s+", " ", txt).strip()[:80]


def analizar_archivo(f: Path, corta: str) -> dict:
    src = f.read_text(encoding="utf-8", errors="replace")
    res: dict = {"fn": [], "models": [], "routes": [], "vars": [], "endpoints": [], "tags": ["activo"]}
    tipo = tipo_de_archivo(corta)
    vistos: set = set()

    for m in _RE_FUNC.finditer(src):
        nombre = m.group(3) or ("default" if m.group(1) else None)
        if not nombre or nombre in vistos:
            continue
        vistos.add(nombre)
        if tipo == "route" and nombre in METODOS_HTTP:
            continue  # va como endpoint
        res["fn"].append([f"{nombre}({_args(m.group(4))})", _doc_previa(src, m.start())])

    for m in _RE_CONST_FN.finditer(src):
        nombre = m.group(1)
        if nombre in vistos:
            continue
        vistos.add(nombre)
        if tipo == "route" and nombre in METODOS_HTTP:
            continue
        res["fn"].append([f"{nombre}({_args(m.group(3) or m.group(4))})", _doc_previa(src, m.start())])

    for m in _RE_CONST.finditer(src):
        nombre = m.group(1)
        if nombre in vistos:
            continue
        vistos.add(nombre)
        valor = m.group(2).strip()
        res["vars"].append([nombre, valor[:48] + ("…" if len(valor) > 48 else "")])

    for m in _RE_TIPO.finditer(src):
        res["vars"].append([m.group(1), "tipo"])

    url = _url_de(corta)
    if url is not None:
        if tipo == "page":
            res["routes"].append([f"GET {url}", "página"])
            res["endpoints"].append({"method": "PÁGINA", "path": url, "owner": "app", "fn": "default", "doc": _doc_previa(src, 0)})
        elif tipo == "route":
            for met in METODOS_HTTP:
                if re.search(rf"^\s*export\s+(?:async\s+)?(?:function\s+{met}\b|const\s+{met}\b)", src, re.M):
                    res["routes"].append([f"{met} {url}", "API"])
                    res["endpoints"].append({"method": met, "path": url, "owner": "app", "fn": met, "doc": ""})

    if _RE_USE_CLIENT.search(src):
        res["tags"].append("cliente")
    if _RE_USE_SERVER.search(src):
        res["tags"].append("servidor")
    if tipo != "modulo":
        res["tags"].append(tipo)
    return res


def modelos_prisma(raiz: Path) -> list:
    """`model X { campo Tipo ... }` de prisma/schema.prisma → [[X, 'campo, campo']]."""
    esquema = raiz / "prisma" / "schema.prisma"
    if not esquema.exists():
        return []
    src = esquema.read_text(encoding="utf-8", errors="replace")
    out = []
    for m in re.finditer(r"^model\s+(\w+)\s*\{([\s\S]*?)^\}", src, re.M):
        campos = []
        for linea in m.group(2).splitlines():
            t = linea.strip()
            if not t or t.startswith("//") or t.startswith("@@"):
                continue
            campos.append(t.split()[0])
        out.append([m.group(1), ", ".join(campos)])
    return out


# ---------------------------------------------------------------- imports --

_RE_IMPORTS = [
    re.compile(r"""^\s*(?:import|export)\s[^;'"]*?\sfrom\s+["']([^"']+)["']""", re.M),
    re.compile(r"""^\s*import\s+["']([^"']+)["']""", re.M),
    re.compile(r"""import\(\s*["']([^"']+)["']\s*\)"""),
]


def _alias(raiz: Path) -> list[tuple[str, Path]]:
    """Alias de `compilerOptions.paths` de tsconfig/jsconfig. `@/*` → src/."""
    for nombre in ("tsconfig.json", "jsconfig.json"):
        cfg = raiz / nombre
        if not cfg.exists():
            continue
        try:
            # tsconfig admite comentarios y comas finales. Los comentarios se sacan
            # solo fuera de strings: "@/*" parece el inicio de un /* ... */ y un
            # regex ingenuo se comía medio archivo (el alias quedaba vacío).
            txt = re.sub(r'("(?:\\.|[^"\\])*")|//[^\n]*|/\*[\s\S]*?\*/',
                         lambda m: m.group(1) or "", cfg.read_text(encoding="utf-8"))
            txt = re.sub(r",(\s*[}\]])", r"\1", txt)
            opts = json.loads(txt).get("compilerOptions", {})
        except (OSError, ValueError):
            continue
        base = raiz / opts.get("baseUrl", ".")
        out = []
        for patron, destinos in (opts.get("paths") or {}).items():
            if destinos:
                out.append((patron.rstrip("*"), (base / destinos[0].rstrip("*")).resolve()))
        return out
    return []


def _resolver(esp: str, desde: Path, alias: list, indice: dict) -> str | None:
    if esp.startswith("."):
        base = (desde.parent / esp).resolve()
    else:
        base = None
        for prefijo, destino in alias:
            if esp.startswith(prefijo):
                base = (destino / esp[len(prefijo):]).resolve()
                break
        if base is None:
            return None  # paquete externo
    candidatos = [base] + [base.with_name(base.name + e) for e in EXTS] + [base / f"index{e}" for e in EXTS]
    for c in candidatos:
        mid = indice.get(str(c))
        if mid:
            return mid
    return None


def grafo_imports(archivos: dict, raiz: Path) -> dict:
    """{mid: [mid destino]} a partir de las líneas import/export ... from."""
    alias = _alias(raiz)
    indice = {str(f.resolve()): mid for mid, f in archivos.items()}
    grafo: dict = {}
    for mid, f in archivos.items():
        src = f.read_text(encoding="utf-8", errors="replace")
        destinos = []
        for rx in _RE_IMPORTS:
            for m in rx.finditer(src):
                t = _resolver(m.group(1), f, alias, indice)
                if t and t != mid and t not in destinos:
                    destinos.append(t)
        if destinos:
            grafo[mid] = destinos
    return grafo


# ------------------------------------------------------------------ pilares --

def pilar_de(corta: str) -> str:
    p = PurePosixPath(corta).parts
    if not p:
        return "backbone"
    if p[0] == "app":
        return "integradores" if "api" in p[1:-1] else "rutas"
    if p[0] == "components":
        return "interfaz"
    if p[0] == "prisma":
        return "datos"
    if p[0] in ("lib", "utils", "hooks") or p[0] in ("middleware.ts", "instrumentation.ts"):
        return "backbone"
    return "herramientas"


# ---------------------------------------------------------------- secciones --

def secciones(children_por_url: list) -> dict:
    """Vista Secciones: el espacio de URLs, agrupado por tramo (mismo formato que Python)."""
    if not children_por_url:
        return {}
    raiz = "/"
    groups = {raiz: {"id": raiz, "label": "/", "parent": None, "depth": 0}}

    def asegurar(tramos):
        padre, acc = raiz, []
        for depth, parte in enumerate(tramos, start=1):
            acc.append(parte)
            gid = raiz + "/".join(acc)
            if gid not in groups:
                groups[gid] = {"id": gid, "label": parte, "parent": padre, "depth": depth, "sin_resolver": False}
            padre = gid
        return padre

    for u in children_por_url:
        tramos = [t for t in u["url"].split("/") if t]
        asegurar(tramos[:-1])
    children = []
    for u in children_por_url:
        tramos = [t for t in u["url"].split("/") if t]
        gid = raiz + "/".join(tramos)
        if tramos and gid in groups:
            grupo, etiqueta = gid, f"{u['method']} /"
        else:
            grupo = asegurar(tramos[:-1])
            etiqueta = f"{u['method']} /{tramos[-1]}" if tramos else f"{u['method']} /"
        children.append({
            "id": f"{u['method']} {u['url']}@{u['module_id']}",
            "node_id": u["module_id"],
            "label": etiqueta,
            "group": grupo,
            "url": u["url"],
            "fn": u["fn"],
            "desc": u["doc"] or f"{u['method']} {u['url']}",
            "rel_path": u["rel_path"],
            "tags": [],
        })
    top = sorted(g["id"] for g in groups.values() if g["depth"] == 1)
    for i, gid in enumerate(top):
        groups[gid]["color"] = _GROUP_COLORS[i % len(_GROUP_COLORS)]
    return {"groups": list(groups.values()), "children": children}


# ------------------------------------------------------------------ diseño --
# La web como la ve quien la visita: cada página con sus bloques en orden. Un
# bloque es una `<section>` de primer nivel (su nombre sale del comentario JSX de
# la línea anterior) o un componente propio de primer nivel que se cierra solo
# (`<Nav />`, `<EscenaAtalaya />`, `<Footer />`). El sub-componente que viaja al
# puente es `#id` para una sección con id fijo, `/* texto` para una sin id, o el
# nombre del componente, que el puente resuelve contra el archivo en disco.

_RE_COMENTARIO_JSX = re.compile(r"^\s*\{/\*\s*(.*?)\s*\*/\}\s*$")
_RE_TAG_COMPONENTE = re.compile(r"<([A-Z][A-Za-z0-9_]*)\b[^<>]*?/>")
_RE_IMPORT_NOMBRES = re.compile(r"""^\s*import\s+(?:type\s+)?(?:([A-Za-z_$][\w$]*)\s*,?\s*)?(?:\{([^}]*)\})?\s*from\s+["']([^"']+)["']""", re.M)


# Nombres legibles para los componentes genéricos de un sitio
_NOMBRES_COMPONENTE = {
    "Nav": "Menú", "Navbar": "Menú", "Header": "Encabezado", "ServicioHeader": "Encabezado",
    "Footer": "Pie", "Contact": "Contacto", "Contacto": "Contacto", "CtaFinal": "Llamado final",
}


def _nombre_legible(txt: str, marcas: set = frozenset()) -> str:
    """
    'QUÉ OFRECEMOS' → 'Qué ofrecemos'; corta en el primer ':' y limita el largo.
    Si el texto está mayormente en mayúsculas se pasa a oración, pero se respetan
    las palabras que el proyecto escribe siempre en mayúsculas (ATALAYA).
    """
    t = txt.split(":")[0].strip().rstrip(".")
    letras = [c for c in t if c.isalpha()]
    if letras and sum(c.isupper() for c in letras) / len(letras) >= 0.7:
        palabras = []
        for k, w in enumerate(t.split(" ")):
            limpia = re.sub(r"[^\wÁÉÍÓÚÑáéíóúñ]", "", w)
            if limpia and limpia.upper() in marcas:
                palabras.append(w)
            else:
                palabras.append(w[:1] + w[1:].lower() if k == 0 else w.lower())
        t = " ".join(palabras)
    return t[:48]


def _imports_locales(src: str, f: Path, alias: list, indice: dict) -> dict:
    """{NombreImportado: mid} de los imports que resuelven a un archivo del proyecto."""
    out = {}
    for m in _RE_IMPORT_NOMBRES.finditer(src):
        mid = _resolver(m.group(3), f, alias, indice)
        if not mid:
            continue
        if m.group(1):
            out[m.group(1)] = mid
        for parte in (m.group(2) or "").split(","):
            nombre = parte.strip().split(" as ")[-1].strip()
            if nombre and not nombre.startswith("type "):
                out[nombre] = mid
    return out


def _comentario_cercano(lineas: list, i: int, alcance: int = 40):
    """Comentario JSX en la línea anterior, o hasta `alcance` líneas arriba si en el
    medio no hay otra sección (el caso de `{lista.map(... <section`)."""
    for k in range(i - 1, max(-1, i - 1 - alcance), -1):
        l = lineas[k]
        if not l.strip():
            continue
        m = _RE_COMENTARIO_JSX.match(l)
        if m:
            return m
        if "</section>" in l or "<section" in l:
            return None
    return None


def bloques_de_pagina(f: Path, alias: list, indice: dict, marcas: set = frozenset()) -> list:
    src = f.read_text(encoding="utf-8", errors="replace")
    locales = _imports_locales(src, f, alias, indice)
    lineas = src.splitlines()
    bloques, prof = [], 0
    for i, linea in enumerate(lineas):
        abre = len(re.findall(r"<section\b", linea))
        cierra = len(re.findall(r"</section>", linea))
        if prof == 0 and abre:
            mc = _comentario_cercano(lineas, i)
            mid_ = re.search(r'\bid="([^"]+)"', linea)
            if mid_:
                sub = f"#{mid_.group(1)}"
            elif mc:
                sub = f"/* {mc.group(1)[:40]}"
            else:
                sub = None
            nombre = _nombre_legible(mc.group(1), marcas) if mc else (f"#{mid_.group(1)}" if mid_ else "Sección")
            bloques.append({"tipo": "seccion", "nombre": nombre, "sub": sub,
                            "ancla": f"#{mid_.group(1)}" if mid_ else ""})
        elif prof == 0:
            for m in _RE_TAG_COMPONENTE.finditer(linea):
                comp = m.group(1)
                if comp in locales:
                    previa = next((lineas[k] for k in range(i - 1, -1, -1) if lineas[k].strip()), "")
                    mc = _RE_COMENTARIO_JSX.match(previa)
                    nombre = (_nombre_legible(mc.group(1), marcas) if mc
                              else _NOMBRES_COMPONENTE.get(comp, comp))
                    bloques.append({"tipo": "componente", "nombre": nombre,
                                    "sub": comp, "mid": locales[comp], "ancla": ""})
        prof = max(0, prof + abre - cierra)
    return bloques


def _marcas(archivos: dict) -> set:
    """Palabras que el proyecto escribe en mayúsculas dentro de strings (ATALAYA)."""
    out: set = set()
    for f in archivos.values():
        for lit in re.findall(r'"([^"\n]{2,80})"', f.read_text(encoding="utf-8", errors="replace")):
            for w in re.findall(r"\b[A-ZÁÉÍÓÚÑ]{3,}\b", lit):
                out.add(w)
    return out


def vista_diseno(paginas: list, alias: list, indice: dict, reales: dict, marcas: set = frozenset()) -> dict:
    """{groups, children} con un grupo por página y sus bloques en orden."""
    if not paginas:
        return {}
    raiz = "/"
    groups = {raiz: {"id": raiz, "label": "whitetec", "parent": None, "depth": 0}}
    children = []
    for url, mid, f in sorted(paginas, key=lambda t: (t[0] != "/", t[0])):
        gid = f"pagina:{url}"
        bloques = bloques_de_pagina(f, alias, indice, marcas)
        if not bloques:
            continue  # una página sin bloques de primer nivel no aporta una caja vacía
        groups[gid] = {"id": gid, "label": url, "parent": raiz, "depth": 1}
        # Número con dos dígitos: la vista de contención ordena por etiqueta y
        # "10 ·" quedaba antes que "2 ·".
        for n, b in enumerate(bloques, start=1):
            destino = b.get("mid", mid)
            children.append({
                "id": f"{url}#{n}",
                "node_id": destino,
                "label": f"{n:02d} · {b['nombre']}",
                "group": gid,
                "url": url + (b["ancla"] if b["ancla"] else ""),
                "fn": b["sub"],
                "desc": (f"Componente {b['sub']} ({reales.get(destino, destino)})" if b["tipo"] == "componente"
                         else f"Sección {b['ancla'] or ''} de {url}".replace("  ", " ")),
                "rel_path": reales.get(destino, ""),
                "tags": [b["tipo"]],
            })
    top = sorted(g["id"] for g in groups.values() if g["depth"] == 1)
    for i, gid in enumerate(top):
        groups[gid]["color"] = _GROUP_COLORS[i % len(_GROUP_COLORS)]
    return {"groups": list(groups.values()), "children": children}


# ---------------------------------------------------------------- pipeline --

def generate_nextjs(app_dir: Path, depth: str = "basico", app_display: str = "") -> tuple:
    """Retorna (graph, detail, stack, cantidad) con el mismo contrato que los otros pipelines."""
    raiz = encontrar_raiz(app_dir)
    if raiz is None:
        raise ValueError("no se encontró un package.json con next")

    archivos: dict = {}      # mid → Path
    modules: list = []
    detail: dict = {}
    urls: list = []

    for f in encontrar_archivos(raiz):
        corta = ruta_corta(f, raiz)
        mid = re.sub(r"\.(tsx?|jsx?|mjs)$", "", corta)
        real = f.relative_to(app_dir).as_posix()
        info = analizar_archivo(f, corta)
        tipo = tipo_de_archivo(corta)
        url = _url_de(corta)
        if tipo in ("page", "route", "layout") and url is not None:
            etiqueta = f"{f.name} {url}"
        else:
            etiqueta = f.name
        archivos[mid] = f
        detail[mid] = info
        modules.append({"id": mid, "label": etiqueta, "desc": f"Módulo {real}",
                        "tags": info["tags"], "rel_path": corta, "_real": real})
        for ep in info["endpoints"]:
            urls.append({"method": ep["method"], "url": ep["path"], "module_id": mid,
                         "fn": ep["fn"], "doc": ep["doc"], "rel_path": real})

    # Modelos de Prisma en un nodo propio (el esquema no es TS)
    modelos = modelos_prisma(raiz)
    if modelos:
        esquema = raiz / "prisma" / "schema.prisma"
        corta = ruta_corta(esquema, raiz)
        mid = "prisma/schema.prisma"
        detail[mid] = {"fn": [], "models": modelos, "routes": [], "vars": [], "endpoints": [], "tags": ["activo", "esquema"]}
        modules.append({"id": mid, "label": "schema.prisma", "desc": f"Módulo {esquema.relative_to(app_dir).as_posix()}",
                        "tags": ["activo", "esquema"], "rel_path": corta, "_real": esquema.relative_to(app_dir).as_posix()})

    calls = grafo_imports(archivos, raiz)
    pillar_map = {m["id"]: pilar_de(m["rel_path"]) for m in modules}
    graph = build_graph(modules, pillar_map, build_dep_edges_from_calls(calls), app_display)

    # Los grupos se arman con la ruta corta (sin `sitio/src/`), pero el puente
    # necesita la ruta real relativa a la app para abrir el archivo.
    reales = {m["id"]: m["_real"] for m in modules}
    for c in graph["children"]:
        c["rel_path"] = reales.get(c["id"], c["rel_path"])
    graph["artifacts"] = []

    for mid, info in detail.items():
        info["calls"] = calls.get(mid, [])
    vista = secciones(urls)
    if vista:
        detail.setdefault("_views", {})["secciones"] = vista

    alias = _alias(raiz)
    indice = {str(f.resolve()): mid for mid, f in archivos.items()}
    paginas = [(_url_de(ruta_corta(f, raiz)), mid, f) for mid, f in archivos.items()
               if tipo_de_archivo(ruta_corta(f, raiz)) == "page" and _url_de(ruta_corta(f, raiz)) is not None]
    diseno = vista_diseno(paginas, alias, indice, reales, _marcas(archivos))
    if diseno:
        detail.setdefault("_views", {})["diseño"] = diseno

    stack = f"nextjs {_version_next(raiz)}".strip()
    return graph, detail, stack, len(modules)
