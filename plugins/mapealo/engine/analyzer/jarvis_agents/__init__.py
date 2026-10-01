"""Analyzer jarvis-agents — entry point: generate_jarvis_agents(app_dir, depth, app_display).

Mapea un ecosistema de agentes. La fuente vive fuera de `app_dir`, y hay dos:

  `fichas`  las fichas del operador (`~/jarvis-director/agentes/*.md`), que
            traen taxonomía propia: Tipo, Capability, Autonomy.
  `auto`    autodetección por las convenciones de Claude Code (agents, skills,
            commands, plugins, MCP, hooks, CLAUDE.md). Ver `discovery.py`.

Se elige sola: si hay fichas parseables, `fichas`; si no, `auto`. Forzable con
`"discovery": "auto"|"fichas"` en `jarvis-map.json`. En modo `auto`, las fichas
que existan enriquecen los agentes detectados en vez de reemplazarlos.

`app_dir` solo contiene `jarvis-map.json` con los paths origen y APP.md/CHANGELOG.md
para que el resto de la app se comporte como cualquier otra del catálogo.
"""
import re
from pathlib import Path

from analyzer import load_config
from analyzer.jarvis_agents.parser    import parse_fichas
from analyzer.jarvis_agents.perfil    import parse_perfil
from analyzer.jarvis_agents.builder   import (
    build_agents_graph, CC_PILLAR_META, CC_PILLAR_ORDER,
)
from analyzer.jarvis_agents import discovery


def generate_jarvis_agents(app_dir: Path, depth: str, app_display: str) -> tuple:
    """Pipeline jarvis-agents. Retorna (graph, detail, stack, count)."""
    cfg         = load_config(app_dir)
    agentes_dir = _expand(cfg.get("agentes_dir", "~/jarvis-director/agentes/"))
    fichas      = parse_fichas(agentes_dir)

    mode = cfg.get("discovery") or ("fichas" if fichas else "auto")
    if mode == "auto":
        return _generate_auto(depth, app_display, fichas)

    return _generate_fichas(fichas, depth, app_display)


def _generate_fichas(fichas: list, depth: str, app_display: str) -> tuple:
    """Pipeline sobre las fichas del operador — taxonomía META/T/AE/C."""

    detail: dict     = {}
    components: list = []
    pillar_map: dict = {}

    for f in fichas:
        slug = f["slug"]
        tipo = f["tipo"] or "T"  # fallback razonable
        components.append({
            "id":       slug,
            "label":    slug,
            "rel_path": f["rel_path"],
            "tags":     _agent_tags(f),
            "desc":     f.get("especialidad", ""),
        })
        pillar_map[slug] = tipo
        detail[slug]     = _agent_detail(f)

    deps: list = []
    if depth == "profundo":
        deps = _infer_deps(fichas)
        # Sub-agentes anidados declarados en la tabla de la ficha
        for f in fichas:
            for sub in f.get("subagentes", []):
                sid = sub["slug"]
                if sid in pillar_map:
                    continue
                components.append({
                    "id":       sid,
                    "label":    sid,
                    "rel_path": "",
                    "tags":     ["sub", "remoto"],
                    "desc":     sub.get("especialidad", ""),
                })
                pillar_map[sid] = pillar_map.get(f["slug"], "C")
                detail[sid] = {
                    "sections": [{
                        "label":      "Información",
                        "chip_class": "chip-var",
                        "items": [
                            ["Sub-agente",          "Tipo"],
                            [sub.get("especialidad",""), "Especialidad"],
                            [f["slug"],             "Padre"],
                        ],
                    }],
                    "tags": ["sub"],
                }
                deps.append({"source": sid, "target": f["slug"]})

    graph = build_agents_graph(components, pillar_map, deps, app_display)
    graph["artifacts"] = []
    return graph, detail, "jarvis-agents", len(components)


# ─── pipeline autodetectado ─────────────────────────────────────────────────

# Filas de la ficha que enriquecen un agente detectado: ninguna convención
# estándar expresa Tipo, Capability ni Autonomy.
_FICHA_EXTRA = [
    ("tipo",         "Tipo"),
    ("especialidad", "Especialidad"),
    ("capability",   "Capability"),
    ("autonomy",     "Autonomy"),
    ("objeto",       "Objeto"),
]


def _generate_auto(depth: str, app_display: str, fichas: list) -> tuple:
    """Pipeline sobre el ecosistema autodetectado — taxonomía por fuente."""
    eco   = discovery.detect_ecosystem()
    comps = eco["components"]

    _enrich_with_fichas(comps, fichas)
    _assign_unique_ids(comps)

    components: list = []
    pillar_map: dict = {}
    detail:     dict = {}

    for c in comps:
        cid = c["node_id"]
        components.append({
            "id":       cid,
            "label":    c["label"],
            "rel_path": c["path"],
            "tags":     c["tags"],
            "desc":     c["desc"],
        })
        pillar_map[cid] = c["pillar"]
        detail[cid]     = _auto_detail(c)

    deps = _infer_deps_auto(comps) if depth == "profundo" else []

    graph = build_agents_graph(
        components, pillar_map, deps, app_display,
        pillar_meta=CC_PILLAR_META, pillar_order=CC_PILLAR_ORDER,
    )
    graph["artifacts"] = []
    graph["discovery"] = eco["sources"]
    return graph, detail, "claude-code-agents", len(components)


def _enrich_with_fichas(comps: list, fichas: list) -> None:
    """Suma los campos de la ficha al agente detectado con el mismo nombre."""
    by_slug = {f["slug"]: f for f in fichas}
    if not by_slug:
        return
    for c in comps:
        f = by_slug.get(c["id"])
        if not f or c["pillar"] != discovery.P_AGENT:
            continue
        extra = [[f[k], label] for k, label in _FICHA_EXTRA if f.get(k)]
        c["items"] = extra + c["items"]
        if not c["desc"]:
            c["desc"] = f.get("especialidad", "")
        if "ficha" not in c["tags"]:
            c["tags"] = c["tags"] + ["ficha"]
        perfil = _expand((f.get("perfil_path") or "").split()[0]) if f.get("perfil_path") else None
        c["perfil_path"] = str(perfil) if perfil and perfil.is_file() else ""


def _assign_unique_ids(comps: list) -> None:
    """Id único por nodo del grafo. El mismo nombre puede ser skill y plugin
    a la vez (una skill que viene empaquetada en un plugin homónimo); el grafo
    se indexa por id, así que la colisión tiene que romperse acá."""
    counts: dict = {}
    for c in comps:
        counts[c["id"]] = counts.get(c["id"], 0) + 1
    for c in comps:
        c["node_id"] = c["id"] if counts[c["id"]] == 1 else f"{c['id']} ({c['pillar']})"


_CHIP_BY_PILLAR = {
    discovery.P_AGENT:   "chip-var",
    discovery.P_SKILL:   "chip-route",
    discovery.P_COMMAND: "chip-fn",
    discovery.P_PLUGIN:  "chip-model",
    discovery.P_MCP:     "chip-model",
    discovery.P_HOOK:    "chip-var",
}


def _auto_detail(c: dict) -> dict:
    """Secciones data-driven del componente detectado."""
    sections = [{
        "label":      "Información",
        "chip_class": _CHIP_BY_PILLAR.get(c["pillar"], "chip-var"),
        "items":      c["items"] or [[c["pillar"], "Tipo"]],
    }]

    if c["desc"]:
        sections.append({
            "label":      "Descripción",
            "chip_class": "chip-route",
            "items":      [[c["desc"], ""]],
        })

    perfil = c.get("perfil_path")
    if perfil:
        data = parse_perfil(Path(perfil))
        habilidades = data.get("habilidades") or []
        if habilidades:
            sections.append({
                "label":      "Habilidades",
                "chip_class": "chip-route",
                "items":      [[f"{h['id']} · {h['label']}", h["accion"]] for h in habilidades],
            })
        herramientas = data.get("herramientas") or []
        if herramientas:
            sections.append({
                "label":      "Herramientas",
                "chip_class": "chip-model",
                "items":      [[t, ""] for t in herramientas],
            })

    return {"sections": sections, "tags": c["tags"] or ["activo"]}


def _infer_deps_auto(comps: list) -> list:
    """Aristas del ecosistema detectado, de tres clases:

      pertenencia  una skill de plugin cuelga de su plugin
      scope        un componente de proyecto cuelga del agente de ese proyecto
      referencia   el cuerpo de un .md nombra a otro componente
    """
    by_name: dict = {}
    for c in comps:
        by_name.setdefault(c["id"], c)

    edges: list = []
    seen:  set  = set()

    def add(src: str, dst: str):
        if src == dst or (src, dst) in seen:
            return
        seen.add((src, dst))
        edges.append({"source": src, "target": dst})

    for c in comps:
        scope_kind, _, scope_name = c["scope"].partition(':')
        if scope_name:
            owner = by_name.get(scope_name)
            if owner is not None:
                add(c["node_id"], owner["node_id"])

    # Referencias cruzadas: solo nombres de 4+ chars para no emparejar ruido.
    targets = {
        name: c for name, c in by_name.items()
        if len(name) >= 4 and not name.startswith('/')
    }
    patterns = {
        name: re.compile(r'(?<![\w/-])' + re.escape(name) + r'(?![\w-])')
        for name in targets
    }
    for c in comps:
        path = Path(c["path"]) if c["path"] else None
        if path is None or not path.is_file() or path.suffix != ".md":
            continue
        try:
            body = path.read_text(encoding='utf-8', errors='replace')[:discovery._MAX_READ]
        except OSError:
            continue
        for name, target in targets.items():
            if name == c["id"]:
                continue
            if patterns[name].search(body):
                add(c["node_id"], target["node_id"])
    return edges


def _expand(path_str: str) -> Path:
    return Path(path_str).expanduser()


def _agent_tags(f: dict) -> list:
    tags = []
    auto = f.get("autonomy")
    if auto:
        tags.append(auto.lower())
    cap = f.get("capability")
    if cap:
        tags.append(f"cap-{cap.replace('/', '-')}")
    if f.get("destinatario"):
        tags.append("remoto")
    return tags or ["activo"]


def _agent_detail(f: dict) -> dict:
    """Sections data-driven con info de la ficha + habilidades/tools del PERFIL.md."""
    info = []
    for k, label in [
        ("tipo",         "Tipo"),
        ("especialidad", "Especialidad"),
        ("objeto",       "Objeto"),
        ("capability",   "Capability"),
        ("autonomy",     "Autonomy"),
        ("creado",       "Creado"),
        ("destinatario", "Destinatario"),
    ]:
        v = f.get(k)
        if v:
            info.append([v, label])

    # Directorio y PERFIL.md como items clickeables (3er elemento = openPath)
    dir_path     = _resolve_existing_path(f.get("directorio"))
    perfil_path  = _resolve_existing_path(f.get("perfil_path"))
    modules_path = _resolve_existing_path(f.get("modules_path"))
    if f.get("directorio"):
        info.append([f["directorio"], "Directorio", str(dir_path) if dir_path else ""])
    if f.get("perfil_path"):
        info.append([f["perfil_path"], "PERFIL.md", str(perfil_path) if perfil_path else ""])
    if f.get("modules_path"):
        info.append([f["modules_path"], "Módulos", str(modules_path) if modules_path else ""])

    sections = [{"label": "Información", "chip_class": "chip-var", "items": info}]

    perfil_data = parse_perfil(perfil_path) if perfil_path else {}
    habilidades = perfil_data.get("habilidades") or []
    if habilidades:
        sections.append({
            "label":      "Habilidades",
            "chip_class": "chip-route",
            "items":      [[f"{h['id']} · {h['label']}", h["accion"]] for h in habilidades],
        })

    herramientas = perfil_data.get("herramientas") or []
    if herramientas:
        sections.append({
            "label":      "Herramientas",
            "chip_class": "chip-model",
            "items":      [[t, ""] for t in herramientas],
        })

    modules_section = _modules_section(f.get("modules_path"))
    if modules_section:
        sections.append(modules_section)

    decisiones = f.get("decisiones") or []
    if decisiones:
        sections.append({
            "label":      "Decisiones clave",
            "chip_class": "chip-route",
            "items":      [[d, ""] for d in decisiones[-5:]],
        })

    subs = f.get("subagentes") or []
    if subs:
        sections.append({
            "label":      "Sub-agentes",
            "chip_class": "chip-fn",
            "items":      [[s["slug"], s.get("especialidad", "")] for s in subs],
        })

    return {"sections": sections, "tags": ["activo"]}


def _resolve_existing_path(raw: str | None) -> Path | None:
    """Expande ~ y devuelve Path absoluto si existe, sino None. Toma solo el primer token."""
    if not raw:
        return None
    token = raw.split()[0]
    p = _expand(token)
    return p if p.exists() else None


def _modules_section(modules_path: str | None) -> dict | None:
    """Lista los .md del directorio de instructions del agente. Cada chip abre su archivo."""
    if not modules_path:
        return None
    raw = modules_path.split()[0] if modules_path else ""
    if not raw:
        return None
    p = _expand(raw)
    if not p.is_dir():
        return {
            "label":      "Módulos cargables",
            "chip_class": "chip-var",
            "items":      [["(no instalado en esta máquina)", str(p)]],
        }
    files = sorted(p.glob("*.md"))
    if not files:
        return None
    return {
        "label":      "Módulos cargables",
        "chip_class": "chip-fn",
        "items":      [[md.name, "", str(md)] for md in files],
    }


def _infer_deps(fichas: list) -> list:
    """
    Pertenencia agente → meta-agente: todo agente no-META cuelga de
    `jarvis-director`. Los META no se conectan a sí mismos.
    """
    slugs = {f["slug"] for f in fichas}
    edges = []
    for f in fichas:
        if f.get("tipo") == "META":
            continue
        target = "jarvis-director"
        if target in slugs and target != f["slug"]:
            edges.append({"source": f["slug"], "target": target})
    return edges
