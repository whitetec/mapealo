"""Construye graph.json para fuentes WordPress."""
import math

from analyzer.builder import GROUP_ROOT


WP_PILLAR_META = {
    "theme":        {"label": "Theme",         "color": "#bf4b8a", "glow": "#db61a2", "desc": "Theme activo y child themes."},
    "plugins":      {"label": "Plugins",       "color": "#1f6feb", "glow": "#388bfd", "desc": "Plugins instalados."},
    "contenido":    {"label": "Contenido",     "color": "#238636", "glow": "#2ea043", "desc": "CPTs, taxonomías, shortcodes."},
    "integradores": {"label": "Integradores",  "color": "#9e6a03", "glow": "#d29922", "desc": "Adaptadores con sistemas externos."},
    "datos":        {"label": "Datos",         "color": "#6e40c9", "glow": "#8957e5", "desc": "Tablas custom, opciones, transients."},
}


def build_wp_graph(components: list, pillar_map: dict, dep_edges: list, app_display: str) -> dict:
    """
    Layout circular: pilares en círculo, hijos en órbita por pilar.
    Solo emite pilares que tienen al menos un componente.
    """
    used: dict = {}
    for c in components:
        used.setdefault(pillar_map.get(c["id"], "plugins"), []).append(c["id"])

    pillar_nodes = []
    for pid, _kids in used.items():
        meta = WP_PILLAR_META.get(pid) or {"label": pid.title(), "color": "#888", "glow": "#aaa", "desc": ""}
        pillar_nodes.append({"id": pid, **meta})

    np  = len(pillar_nodes)
    cx, cy, r = 500, 380, 260
    for i, p in enumerate(pillar_nodes):
        angle = (2 * math.pi * i / max(np, 1)) - math.pi / 2
        p["position"] = {"x": round(cx + r * math.cos(angle)), "y": round(cy + r * math.sin(angle))}

    pillar_pos = {p["id"]: p["position"] for p in pillar_nodes}
    child_nodes = []
    for pid, kids in used.items():
        px, py = pillar_pos[pid]["x"], pillar_pos[pid]["y"]
        nc = len(kids)
        cr = 155 + nc * 6
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
                "desc":     comp.get("rel_path", ""),
                "rel_path": comp.get("rel_path", ""),
                "position": {"x": cx_c, "y": cy_c},
            })

    # Un sitio WordPress no tiene la jerarquía de directorios de un proyecto
    # Python, así que sus pilares entran como grupos de un solo nivel. Es la
    # misma forma genérica que consume la vista de contención: el frontend no
    # sabe de qué kind viene el mapa.
    groups = [{"id": GROUP_ROOT, "label": app_display or "sitio",
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
