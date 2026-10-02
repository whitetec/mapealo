#!/usr/bin/env python3
"""
mapealo — genera o actualiza el mapa de un proyecto.

Uso:
  python3 mapealo.py <app_id> [--depth basico|profundo] [--force]
  python3 mapealo.py <app_id> --status
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# Asegurar que el directorio del motor esté en sys.path para imports locales
_JMAP_ROOT = os.path.dirname(os.path.abspath(__file__))
if _JMAP_ROOT not in sys.path:
    sys.path.insert(0, _JMAP_ROOT)

from analyzer            import (
    KIND_PYTHON, KIND_WORDPRESS, KIND_WORDPRESS_REMOTE, KIND_AGENTS, KIND_NEXTJS, load_config,
    VALID_KINDS, detect_kind, normalize_kind,
)
from analyzer.artifacts   import detect_artifacts
from analyzer.basic       import analyze_file
from analyzer.builder     import build_dep_edges_from_calls, build_graph
from analyzer.deep        import (
    extract_external_deps, extract_model_relationships, find_test_coverage,
)
from analyzer.imports     import build_import_graph
from analyzer.secciones   import build_secciones
from analyzer.detect      import (
    assign_pillar, detect_flask_blueprints,
    detect_stack, find_python_modules,
)
from version import MAP_SCHEMA, TOOL_VERSION

import paths

_APP_ID_RE   = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$')
_HEADING_RE  = re.compile(r'^# (.+)$', re.MULTILINE)
_CL_DATE_RE  = re.compile(r'###?\s*(\d{4}-\d{2}-\d{2})')


def _validate_app_id(app_id: str) -> None:
    """Valida formato y previene path traversal — comparte regla con app.py.

    Solo aplica a ids. Una ruta explícita pasada por CLI no se valida con esta
    regla: es el camino portable cuando no hay ninguna raíz reconocible, y el
    dueño del filesystem es quien la escribe. La superficie HTTP nunca llega
    acá con una ruta: `app.py` valida con su propia regex antes de invocar.
    """
    if not _APP_ID_RE.match(app_id or "") or app_id.startswith('_'):
        raise ValueError(f"app_id inválido: {app_id!r}")


# Id del stub que aloja el ecosistema de agentes autodetectado.
AGENTS_STUB_ID = "agentes"

_STUB_APP_MD = """# Ecosistema de agentes

Mapa del ecosistema de agentes de esta máquina, descubierto por las
convenciones de Claude Code (`.claude/agents`, `skills`, `commands`,
`plugins`, MCP, hooks y los directorios con `CLAUDE.md`).

Este directorio no es código: lo genera `mapealo.py` para alojar el
`.mapealo/` del mapa. La fuente real vive en `~/.claude/` y en cada
proyecto.
"""


def _bootstrap_agents_stub(app_id: str) -> Path:
    """Crea el stub que aloja el mapa del ecosistema autodetectado.

    El kind `agents` mapea algo que no vive en un directorio propio, así que
    necesita un lugar escribible donde dejar el `.mapealo/`. Sin esto, la
    única forma de pedir el mapa de agentes era crear el stub a mano.
    """
    d = paths.workspace_root() / app_id
    d.mkdir(parents=True, exist_ok=True)
    cfg = d / paths.PROJECT_CONFIG
    if not cfg.exists():
        cfg.write_text(
            json.dumps({"kind": KIND_AGENTS, "discovery": "auto"},
                       ensure_ascii=False, indent=2) + "\n",
            encoding='utf-8',
        )
    app_md = d / "APP.md"
    if not app_md.exists():
        app_md.write_text(_STUB_APP_MD, encoding='utf-8')
    return d


def _resolve(raw: str, kind: str = "auto") -> tuple[str, Path | None]:
    """(app_id, app_dir). app_dir es None si no se encontró en ninguna raíz."""
    app_id  = paths.app_id_for(raw)
    app_dir = paths.resolve_app_dir(raw)
    if app_dir is None and (kind == KIND_AGENTS or app_id == AGENTS_STUB_ID):
        app_dir = _bootstrap_agents_stub(app_id)
    return app_id, app_dir


def _jmap(app_dir: Path) -> Path:
    return paths.out_dir(app_dir)


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}


def _write(path: Path, data: dict):
    """Escritura atómica vía .tmp + os.replace (evita JSON parcial al ser leído)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(tmp, path)


def _last_changelog_date(app_dir: Path) -> str | None:
    cl = app_dir / "CHANGELOG.md"
    if not cl.exists():
        return None
    m = _CL_DATE_RE.search(cl.read_text())
    return m.group(1) if m else None


def _app_display_name(app_dir: Path, fallback: str) -> str:
    app_md = app_dir / "APP.md"
    if app_md.exists():
        m = _HEADING_RE.search(app_md.read_text(encoding='utf-8'))
        if m:
            return m.group(1).strip()
    return fallback


def status(raw: str):
    app_id, app_dir = paths.app_id_for(raw), paths.resolve_app_dir(raw)
    if paths.is_app_id(raw) is False and app_dir is None:
        print(json.dumps({"mapped": False, "app_id": app_id, "error": "app_id inválido"}))
        return
    if app_dir is None:
        print(json.dumps({
            "mapped":  False,
            "app_id":  app_id,
            "error":   f"'{app_id}' no está en ninguna raíz conocida",
            "roots":   [str(r) for r in paths.apps_roots()],
            "hint":    "pasá la ruta del proyecto, o definí MAPEALO_APPS_DIR",
        }))
        return
    jmap    = _jmap(app_dir)
    meta    = _read(jmap / "meta.json")
    cl_date = _last_changelog_date(app_dir)

    if not meta:
        print(json.dumps({"mapped": False, "app_id": app_id}))
        return

    stale = (cl_date or "") > (meta.get("last_changelog_entry") or "")
    print(json.dumps({
        "mapped":               True,
        "depth":                meta.get("depth"),
        "generated_at":         meta.get("generated_at"),
        "last_changelog_entry": meta.get("last_changelog_entry"),
        "latest_changelog":     cl_date,
        "stale":                stale,
        "app_id":               app_id,
    }))


def run_basic(app_dir: Path) -> tuple:
    """Retorna (detail, modules, module_map, stack, pyfiles).

    El id de un módulo es su ruta relativa sin `.py` (`analyzer/wp/builder`).
    Con el stem como id, tres `builder.py` en paquetes distintos colapsaban en
    un solo nodo y sus dependencias se atribuían a cualquiera de los tres.
    """
    stack   = detect_stack(app_dir)
    pyfiles = find_python_modules(app_dir)

    detail: dict  = {}
    modules: list = []

    for pyfile in pyfiles:
        rel   = str(pyfile.relative_to(app_dir))
        mid   = rel[:-3] if rel.endswith(".py") else rel
        info  = analyze_file(pyfile, app_dir)
        info["artifacts"] = detect_artifacts(pyfile)
        detail[mid] = info
        modules.append({
            "id":       mid,
            "label":    pyfile.name,
            "desc":     f"Módulo {rel}",
            "tags":     info.get("tags", ["activo"]),
            "rel_path": rel,
        })

    # stem → id, solo para los nombres que resuelven a un único módulo.
    # Lo consume find_test_coverage, que busca por nombre de archivo.
    stems: dict = {}
    for m in modules:
        stems.setdefault(Path(m["rel_path"]).stem, []).append(m["id"])
    module_map = {s: ids[0] for s, ids in stems.items() if len(ids) == 1}

    return detail, modules, module_map, stack, pyfiles


def run_deep(app_dir: Path, detail: dict, module_map: dict, pyfiles: list,
             calls: dict) -> dict:
    """Agrega capas profundas a `detail` en-place y retorna el call graph."""
    rels     = extract_model_relationships(pyfiles)
    ext_deps = extract_external_deps(app_dir)
    coverage = find_test_coverage(app_dir, module_map)

    for mid, info in detail.items():
        info["calls"]    = calls.get(mid, [])
        info["tests"]    = coverage.get(mid, [])
        info["env_vars"] = []

    detail["_meta_deep"] = {
        "model_relationships": rels,
        "external_deps":       ext_deps,
    }
    return calls


def _build_pillar_map(stack: str, app_dir: Path, modules: list) -> dict:
    """Asigna cada módulo a un pilar — primero blueprints/routers, luego heurística."""
    pillar_map: dict = {}
    if "flask" in stack:
        for bp in detect_flask_blueprints(app_dir):
            pillar_map[bp["id"]] = assign_pillar(bp["id"], bp.get("file", ""))
    if not pillar_map:
        for m in modules:
            pillar_map[m["id"]] = assign_pillar(m["id"], m.get("rel_path", ""))
    return pillar_map


def _build_artifacts(modules: list, detail: dict) -> list:
    """Deduplica artefactos por (op, path_hint) y registra qué módulos los tocan."""
    artifact_map: dict = {}
    for m in modules:
        mid = m["id"]
        for art in detail.get(mid, {}).get("artifacts", []):
            key = (art["op"], art["path_hint"])
            slot = artifact_map.setdefault(key, {
                "id":            f"_art_{len(artifact_map)}",
                "op":            art["op"],
                "path_hint":     art["path_hint"],
                "artifact_type": art["artifact_type"],
                "modules":       [],
            })
            if mid not in slot["modules"]:
                slot["modules"].append(mid)
    return list(artifact_map.values())


def _merge_layout(existing_graph: dict, fresh_graph: dict) -> dict:
    """
    Merge curado:
      - preserva position de pillars y children existentes
      - recomputa label, desc, color, glow, parent, tags (vienen de fresh)
      - agrega children/pillars nuevos con su posición orbital
      - elimina children huérfanos
    """
    old_pillar_pos   = {p["id"]: p.get("position") for p in existing_graph.get("pillars",  [])}
    old_child_pos    = {c["id"]: c.get("position") for c in existing_graph.get("children", [])}

    for p in fresh_graph["pillars"]:
        if p["id"] in old_pillar_pos and old_pillar_pos[p["id"]]:
            p["position"] = old_pillar_pos[p["id"]]
    for c in fresh_graph["children"]:
        if c["id"] in old_child_pos and old_child_pos[c["id"]]:
            c["position"] = old_child_pos[c["id"]]

    return fresh_graph


def _generate_python(app_dir: Path, depth: str, is_upgrade: bool, app_display: str) -> tuple:
    """Pipeline Python — retorna (graph, detail, stack, modules_count)."""
    detail, modules, module_map, stack, pyfiles = run_basic(app_dir)
    pillar_map = _build_pillar_map(stack, app_dir, modules)

    # El grafo de imports es barato y es lo que vuelve legible al mapa, así que
    # se calcula siempre. `profundo` queda para lo caro: modelos, tests y deps
    # externas. Antes las dependencias solo existían con --depth profundo, y un
    # mapa basico era una lista de archivos sin una sola flecha.
    calls = build_import_graph(modules, app_dir)
    if depth == "profundo" or is_upgrade:
        run_deep(app_dir, detail, module_map, pyfiles, calls)

    dep_edges = build_dep_edges_from_calls(calls)
    graph     = build_graph(modules, pillar_map, dep_edges, app_display)
    graph["artifacts"] = _build_artifacts(modules, detail)

    # Vista Secciones: el espacio de URLs de la app. Solo existe si hay rutas,
    # así que una app sin interfaz web no muestra la pestaña.
    secciones = build_secciones(app_dir, modules, detail)
    if secciones:
        detail.setdefault("_views", {})["secciones"] = secciones

    return graph, detail, stack, len(modules)


def _generate_wordpress(app_dir: Path, depth: str, is_upgrade: bool, app_display: str) -> tuple:
    """Pipeline WordPress (PHP local) — retorna (graph, detail, stack, components_count)."""
    from analyzer.wp import generate_wp
    return generate_wp(app_dir, depth=depth, app_display=app_display)


def _generate_wordpress_remote(app_dir: Path, depth: str, is_upgrade: bool, app_display: str) -> tuple:
    """Pipeline WordPress remoto (WP-CLI vía SSH) — retorna (graph, detail, stack, count)."""
    from analyzer.wp_remote import generate_wp_remote
    return generate_wp_remote(app_dir, depth=depth, app_display=app_display)


def _generate_agents(app_dir: Path, depth: str, is_upgrade: bool, app_display: str) -> tuple:
    """Pipeline de ecosistemas de agentes — retorna (graph, detail, stack, count)."""
    from analyzer.agents import generate_agents
    return generate_agents(app_dir, depth=depth, app_display=app_display)


def _generate_nextjs(app_dir: Path, depth: str, is_upgrade: bool, app_display: str) -> tuple:
    """Pipeline Next.js (App Router, TS/JS) — retorna (graph, detail, stack, count)."""
    from analyzer.nextjs import generate_nextjs
    return generate_nextjs(app_dir, depth=depth, app_display=app_display)


def generate(raw: str, depth: str, force: bool, kind: str = "auto") -> dict:
    """Genera/actualiza el mapa de una app. Retorna dict con resultado."""
    if paths.is_app_id(raw):
        _validate_app_id(raw)
    app_id, app_dir = _resolve(raw, kind)
    if app_dir is None or not app_dir.is_dir():
        return {
            "error": f"App '{app_id}' no encontrada",
            "roots": [str(r) for r in paths.apps_roots()],
            "hint":  "pasá la ruta del proyecto, o definí MAPEALO_APPS_DIR",
        }

    jmap     = _jmap(app_dir)
    existing = _read(jmap / "meta.json")
    is_upgrade = existing.get("depth") == "basico" and depth == "profundo"

    if kind == "auto":
        # Preferir el kind ya registrado en meta para evitar flapping si la
        # heurística cambia; sino inferir.
        # `mapealo.json` manda sobre el meta: es la forma de corregir un kind
        # mal inferido (whitetec-web quedó como python por sus scripts .py).
        kind = normalize_kind(
            load_config(app_dir).get("kind") or existing.get("kind") or detect_kind(app_dir)
        )
        # Si la heurística no encontró nada concluyente, asumir python:
        # preserva el comportamiento pre-v1.4 y evita 500 en apps vacías.
        if kind == "unknown":
            kind = KIND_PYTHON
    kind = normalize_kind(kind)
    if kind not in VALID_KINDS:
        return {"error": f"kind no soportado: {kind!r} (válidos: {sorted(VALID_KINDS)})"}

    app_display = _app_display_name(app_dir, app_id)

    if kind == KIND_PYTHON:
        fresh_graph, detail, stack, components_count = _generate_python(app_dir, depth, is_upgrade, app_display)
    elif kind == KIND_WORDPRESS:
        fresh_graph, detail, stack, components_count = _generate_wordpress(app_dir, depth, is_upgrade, app_display)
    elif kind == KIND_WORDPRESS_REMOTE:
        try:
            fresh_graph, detail, stack, components_count = _generate_wordpress_remote(
                app_dir, depth, is_upgrade, app_display
            )
        except Exception as e:
            return {"error": f"WordPress remoto falló: {e}"}
    elif kind == KIND_AGENTS:
        fresh_graph, detail, stack, components_count = _generate_agents(
            app_dir, depth, is_upgrade, app_display
        )
    elif kind == KIND_NEXTJS:
        try:
            fresh_graph, detail, stack, components_count = _generate_nextjs(
                app_dir, depth, is_upgrade, app_display
            )
        except ValueError as e:
            return {"error": f"Next.js: {e}"}
    else:
        return {"error": f"kind {kind!r} sin pipeline implementado"}

    fresh_graph["kind"] = kind

    existing_graph = _read(jmap / "graph.json")
    graph = fresh_graph if (force or not existing_graph) else _merge_layout(existing_graph, fresh_graph)

    now  = datetime.now(timezone.utc).isoformat(timespec='seconds')
    meta = {
        "version":              MAP_SCHEMA,
        "tool_version":         TOOL_VERSION,
        "kind":                 kind,
        "depth":                depth,
        "generated_at":         now,
        "last_changelog_entry": _last_changelog_date(app_dir) or "",
        "app_id":               app_id,
        "stack":                stack,
        "modules_count":        components_count,
        "upgraded_from":        existing.get("depth") if is_upgrade else None,
    }

    try:
        _write(jmap / "graph.json",  graph)
        _write(jmap / "detail.json", detail)
        _write(jmap / "meta.json",   meta)
    except PermissionError as e:
        return {"error": f"Sin permisos para escribir en {jmap}: {e}"}

    return {
        "ok":      True,
        "app_id":  app_id,
        "kind":    kind,
        "depth":   depth,
        "modules": components_count,
        "stack":   stack,
        "upgrade": is_upgrade,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Genera el mapa de arquitectura de un proyecto. "
                    "Acepta un id de app o la ruta del proyecto.",
    )
    parser.add_argument("app_id", nargs="?",
                        help="id de app, ruta del proyecto, o 'agentes' "
                             "para el ecosistema de agentes de esta máquina")
    parser.add_argument("--roots", action="store_true",
                        help="imprime las raíces detectadas y las apps visibles, y sale")
    parser.add_argument("--depth",  choices=["basico", "profundo"], default="basico")
    parser.add_argument("--force",  action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--kind",   choices=["auto", KIND_PYTHON, KIND_WORDPRESS, KIND_WORDPRESS_REMOTE, KIND_AGENTS, KIND_NEXTJS,
                                 "jarvis-agents"], default="auto")
    args = parser.parse_args()

    if args.roots:
        print(json.dumps({
            "claude_home": str(paths.claude_home()),
            "roots":       [str(r) for r in paths.apps_roots()],
            "workspace":   str(paths.workspace_root()),
            "apps":        [a for a, _ in paths.list_apps()],
        }, ensure_ascii=False, indent=2))
        return

    if not args.app_id:
        parser.error("falta app_id (o usá --roots)")

    if args.status:
        status(args.app_id)
        return

    try:
        result = generate(args.app_id, args.depth, args.force, kind=args.kind)
    except ValueError as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)

    print(json.dumps(result))
    if "error" in result:
        sys.exit(1)


if __name__ == "__main__":
    main()
