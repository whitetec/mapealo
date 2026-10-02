"""Construye graph.json para un ecosistema de agentes."""
import math

from analyzer.builder import GROUP_ROOT


AGENTS_PILLAR_META = {
    "META": {"label": "Meta",      "color": "#8957e5", "glow": "#a371f7", "desc": "Meta-agentes — arquitectos del sistema."},
    "T":    {"label": "Técnico",   "color": "#1f6feb", "glow": "#388bfd", "desc": "Agentes técnicos — desarrollo, infra, ciberseg."},
    "AE":   {"label": "Analítico", "color": "#238636", "glow": "#2ea043", "desc": "Asistentes analítico-ejecutivos — docs, reportes."},
    "C":    {"label": "Creativo",  "color": "#bf4b8a", "glow": "#db61a2", "desc": "Agentes creativos — multimedia, branding, diseño."},
}

# Orden canónico de pilares para que el layout sea estable entre regeneraciones.
_PILLAR_ORDER = ["META", "T", "AE", "C"]

# Taxonomía del ecosistema autodetectado: el pilar es la fuente de la que sale
# cada componente. Las fichas del operador (META/T/AE/C) no existen en otra
# máquina; estas convenciones de Claude Code sí.
CC_PILLAR_META = {
    "agent":   {"label": "Agentes",  "color": "#8957e5", "glow": "#a371f7", "desc": "Agentes y subagentes — CLAUDE.md propio o definición en .claude/agents/."},
    "skill":   {"label": "Skills",   "color": "#1f6feb", "glow": "#388bfd", "desc": "Skills — capacidades cargables bajo demanda."},
    "command": {"label": "Comandos", "color": "#238636", "glow": "#2ea043", "desc": "Slash commands definidos en .claude/commands/."},
    "plugin":  {"label": "Plugins",  "color": "#9e6a03", "glow": "#d29922", "desc": "Plugins instalados y los marketplaces de los que vienen."},
    "mcp":     {"label": "MCP",      "color": "#bf4b8a", "glow": "#db61a2", "desc": "Servidores MCP — herramientas externas conectadas."},
    "hook":    {"label": "Hooks",    "color": "#1b7c83", "glow": "#39c5cf", "desc": "Eventos del harness con hooks configurados."},
}

CC_PILLAR_ORDER = ["agent", "skill", "command", "plugin", "mcp", "hook"]

_FALLBACK_PILLAR = {"label": "Otros", "color": "#6e7681", "glow": "#8b949e", "desc": "Sin categoría."}


def build_agents_graph(components: list, pillar_map: dict, dep_edges: list, app_display: str,
                       pillar_meta: dict | None = None, pillar_order: list | None = None) -> dict:
    """Layout circular: pilares en círculo, componentes en órbita por pilar.

    `pillar_meta`/`pillar_order` permiten dos taxonomías sobre el mismo layout:
    la de las fichas (META/T/AE/C) y la del ecosistema autodetectado.
    """
    pillar_meta  = pillar_meta  or AGENTS_PILLAR_META
    pillar_order = pillar_order or _PILLAR_ORDER
    default_pid  = pillar_order[0] if pillar_order else "T"

    used: dict = {}
    for c in components:
        pid = pillar_map.get(c["id"], default_pid)
        used.setdefault(pid, []).append(c["id"])

    # Un pilar presente en los datos pero ausente del orden canónico se dibuja
    # al final en vez de desaparecer del mapa.
    ordered = [p for p in pillar_order if p in used]
    ordered += [p for p in sorted(used) if p not in ordered]

    pillar_nodes = []
    for pid in ordered:
        meta = pillar_meta.get(pid) or {**_FALLBACK_PILLAR, "label": str(pid)}
        pillar_nodes.append({"id": pid, **meta})

    np  = len(pillar_nodes)
    cx, cy, r = 500, 380, 260
    for i, p in enumerate(pillar_nodes):
        angle = (2 * math.pi * i / max(np, 1)) - math.pi / 2
        p["position"] = {"x": round(cx + r * math.cos(angle)), "y": round(cy + r * math.sin(angle))}

    pillar_pos = {p["id"]: p["position"] for p in pillar_nodes}
    child_nodes = []
    for pid, kids in used.items():
        if pid not in pillar_pos:
            continue
        px, py = pillar_pos[pid]["x"], pillar_pos[pid]["y"]
        nc = len(kids)
        cr = 155 + nc * 8
        for j, cid in enumerate(kids):
            angle = (2 * math.pi * j / max(nc, 1)) - math.pi / 2
            cx_c  = round(px + cr * math.cos(angle))
            cy_c  = round(py + cr * math.sin(angle))
            comp  = next((c for c in components if c["id"] == cid), {})
            child_nodes.append({
                "id":       cid,
                "label":    comp.get("label", cid),
                "parent":   pid,
                "group":    pid,
                "tags":     comp.get("tags", []),
                "desc":     comp.get("desc", ""),
                "position": {"x": cx_c, "y": cy_c},
            })

    # Las categorías de agente entran como grupos de un solo nivel, igual que
    # los pilares de WordPress: la vista de contención no distingue el kind.
    groups = [{"id": GROUP_ROOT, "label": app_display or "agentes",
               "parent": None, "depth": 0}]
    groups += [{"id": p["id"], "label": p["label"], "parent": GROUP_ROOT,
                "depth": 1, "color": p["color"]} for p in pillar_nodes]

    return {
        "app_display": app_display,
        "pillars":     pillar_nodes,
        "groups":      groups,
        "children":    child_nodes,
        "deps":        dep_edges,
    }
