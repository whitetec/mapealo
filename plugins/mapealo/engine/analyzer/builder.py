"""Construye graph.json con layout automático a partir del análisis."""
import math
from pathlib import PurePosixPath

from .detect import PILLAR_META, assign_pillar


# Colores de fallback para pilares extra
_EXTRA_COLORS = [
    ("#388bfd", "#58a6ff"),
    ("#2ea043", "#56d364"),
    ("#d29922", "#e3b341"),
    ("#8957e5", "#a371f7"),
]

# Paleta de los grupos de primer nivel de la vista Estructura
_GROUP_COLORS = [
    "#1f6feb", "#238636", "#9e6a03", "#6e40c9",
    "#bf4b8a", "#4a7c7e", "#e36209", "#8b5cf6",
]

GROUP_ROOT = "/"


def build_groups(modules: list, app_display: str) -> list:
    """
    Grupos anidados a partir de los directorios reales del proyecto.

    Es la estructura genérica que consume la vista de contención: una lista
    plana de `{id, label, parent, depth}` que el frontend arma como árbol. Un
    analyzer que no tenga jerarquía real (WordPress) emite sus pilares como
    grupos de un solo nivel colgando de la raíz, sin tocar el frontend.
    """
    root = {"id": GROUP_ROOT, "label": app_display or "app",
            "parent": None, "depth": 0}
    groups: dict = {GROUP_ROOT: root}

    for mod in modules:
        parts  = PurePosixPath(mod.get("rel_path", "")).parts[:-1]
        parent = GROUP_ROOT
        acc: list = []
        for depth, part in enumerate(parts, start=1):
            acc.append(part)
            gid = "/".join(acc)
            if gid not in groups:
                groups[gid] = {"id": gid, "label": part,
                               "parent": parent, "depth": depth}
            parent = gid

    # Color estable por grupo de primer nivel; los anidados lo heredan en el front
    top = sorted(g["id"] for g in groups.values() if g["depth"] == 1)
    for i, gid in enumerate(top):
        groups[gid]["color"] = _GROUP_COLORS[i % len(_GROUP_COLORS)]

    return list(groups.values())


def group_of(rel_path: str) -> str:
    """Grupo (directorio) al que pertenece un módulo."""
    parts = PurePosixPath(rel_path or "").parts[:-1]
    return "/".join(parts) if parts else GROUP_ROOT


def build_graph(
    modules: list,       # [{"id": str, "label": str, "desc": str, "tags": [...]}]
    pillar_map: dict,    # {module_id: pillar_id}  — override opcional
    dep_edges: list,     # [{"source": id, "target": id}]
    app_display: str,
) -> dict:
    """Genera graph.json con posiciones automáticas."""

    used_pillars = {}
    for mod in modules:
        pid = pillar_map.get(mod["id"]) or assign_pillar(mod["id"], mod.get("rel_path", ""))
        used_pillars.setdefault(pid, []).append(mod["id"])

    # Construir nodos pilar
    pillar_nodes = []
    extra_idx    = 0
    for pid, children_ids in used_pillars.items():
        meta = PILLAR_META.get(pid)
        if meta:
            color, glow = meta["color"], meta["glow"]
            label, desc = meta["label"], meta["desc"]
        else:
            color, glow = _EXTRA_COLORS[extra_idx % len(_EXTRA_COLORS)]
            extra_idx  += 1
            label, desc = pid.capitalize(), ""
        pillar_nodes.append({
            "id": pid, "label": label, "color": color, "glow": glow, "desc": desc,
        })

    # Posicionar pilares en círculo
    np  = len(pillar_nodes)
    cx, cy, r = 500, 380, 260
    for i, p in enumerate(pillar_nodes):
        angle   = (2 * math.pi * i / np) - math.pi / 2
        p["position"] = {"x": round(cx + r * math.cos(angle)), "y": round(cy + r * math.sin(angle))}

    # Construir nodos hijo con posición orbital alrededor del pilar
    pillar_pos = {p["id"]: p["position"] for p in pillar_nodes}
    child_nodes = []

    for pid, children_ids in used_pillars.items():
        px, py = pillar_pos[pid]["x"], pillar_pos[pid]["y"]
        nc  = len(children_ids)
        cr  = 155 + nc * 8   # radio orbital crece con la cantidad de hijos
        for j, cid in enumerate(children_ids):
            angle = (2 * math.pi * j / max(nc, 1)) - math.pi / 2
            cx_c  = round(px + cr * math.cos(angle))
            cy_c  = round(py + cr * math.sin(angle))
            mod   = next((m for m in modules if m["id"] == cid), {})
            child_nodes.append({
                "id":       cid,
                "label":    mod.get("label", cid),
                "parent":   pid,
                "group":    group_of(mod.get("rel_path", "")),
                "tags":     mod.get("tags", []),
                "desc":     mod.get("desc", ""),
                "rel_path": mod.get("rel_path", ""),
                "position": {"x": cx_c, "y": cy_c},
            })

    return {
        "app_display": app_display,
        "pillars":     pillar_nodes,
        "groups":      build_groups(modules, app_display),
        "children":    child_nodes,
        "deps":        dep_edges,
    }


def build_dep_edges_from_calls(call_graph: dict) -> list:
    """Convierte el call graph de módulos en edges de dependencia."""
    edges = []
    seen  = set()
    for src, targets in call_graph.items():
        for tgt in targets:
            key = (src, tgt)
            if key not in seen:
                edges.append({"source": src, "target": tgt})
                seen.add(key)
    return edges
