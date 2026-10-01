"""Analyzer WordPress — entry point: generate_wp(app_dir, depth, app_display)."""
from pathlib import Path

from analyzer.wp.detect  import detect_plugins, detect_themes
from analyzer.wp.parser  import parse_php_components
from analyzer.wp.builder import build_wp_graph


def generate_wp(app_dir: Path, depth: str, app_display: str) -> tuple:
    """
    Pipeline WordPress básico/profundo.

    v1.4 (alcance): plugins, themes, CPTs, shortcodes.
    v1.4.1+: hooks, taxonomías, REST routes, $wpdb, opciones.

    Retorna (graph, detail, stack, components_count).
    """
    plugins = detect_plugins(app_dir)
    themes  = detect_themes(app_dir)

    # Detail por componente: header WP + lista de CPTs/shortcodes registrados
    detail: dict = {}
    components: list = []

    for p in plugins:
        cid = f"plugin:{p['slug']}"
        php_findings = parse_php_components(p["dir"])
        detail[cid] = _component_detail(
            label=p["meta"].get("Plugin Name") or p["slug"],
            kind_label="Plugin",
            wp_meta=p["meta"],
            cpts=php_findings["cpts"],
            shortcodes=php_findings["shortcodes"],
            rel_path=p["rel_path"],
        )
        components.append({
            "id":       cid,
            "pillar":   "plugins",
            "label":    p["meta"].get("Plugin Name") or p["slug"],
            "rel_path": p["rel_path"],
            "tags":     ["activo"],
        })

    for t in themes:
        cid = f"theme:{t['slug']}"
        php_findings = parse_php_components(t["dir"])
        is_child = bool(t["meta"].get("Template"))
        detail[cid] = _component_detail(
            label=t["meta"].get("Theme Name") or t["slug"],
            kind_label="Theme (child)" if is_child else "Theme",
            wp_meta=t["meta"],
            cpts=php_findings["cpts"],
            shortcodes=php_findings["shortcodes"],
            rel_path=t["rel_path"],
        )
        components.append({
            "id":       cid,
            "pillar":   "theme",
            "label":    t["meta"].get("Theme Name") or t["slug"],
            "rel_path": t["rel_path"],
            "tags":     ["child" if is_child else "parent"],
        })

    # Componentes "contenido": un nodo por CPT y por shortcode globales
    seen_cpt: dict = {}
    seen_sc: dict  = {}
    for c in list(components):  # snapshot
        d = detail[c["id"]]
        for sec in d.get("sections", []):
            if sec["label"] == "CPTs":
                for slug, _ in sec["items"]:
                    if slug not in seen_cpt:
                        seen_cpt[slug] = c["id"]
            elif sec["label"] == "Shortcodes":
                for tag, _ in sec["items"]:
                    if tag not in seen_sc:
                        seen_sc[tag] = c["id"]

    for slug, owner in seen_cpt.items():
        cid = f"cpt:{slug}"
        components.append({
            "id":     cid, "pillar": "contenido",
            "label":  slug, "rel_path": "",
            "tags":   ["cpt"],
            "registered_by": owner,
        })
        detail[cid] = {"sections": [
            {"label": "Tipo", "chip_class": "chip-parent", "items": [["Custom Post Type", ""]]},
            {"label": "Registrado por", "chip_class": "chip-owns", "items": [[owner, ""]]},
        ]}
    for tag, owner in seen_sc.items():
        cid = f"shortcode:{tag}"
        components.append({
            "id":     cid, "pillar": "contenido",
            "label":  f"[{tag}]", "rel_path": "",
            "tags":   ["shortcode"],
            "registered_by": owner,
        })
        detail[cid] = {"sections": [
            {"label": "Tipo", "chip_class": "chip-parent", "items": [["Shortcode", ""]]},
            {"label": "Registrado por", "chip_class": "chip-owns", "items": [[owner, ""]]},
        ]}

    pillar_map = {c["id"]: c["pillar"] for c in components}
    dep_edges  = []
    if depth == "profundo":
        # Edges contenido → plugin/theme que lo registró
        for c in components:
            owner = c.get("registered_by")
            if owner:
                dep_edges.append({"source": c["id"], "target": owner})

    graph = build_wp_graph(components, pillar_map, dep_edges, app_display)
    graph["artifacts"] = []  # v1.4.1: tablas $wpdb, opciones, etc.

    stack = "wordpress"
    return graph, detail, stack, len(components)


def _component_detail(*, label: str, kind_label: str, wp_meta: dict,
                      cpts: list, shortcodes: list, rel_path: str) -> dict:
    """Arma detail con sections data-driven. Pair = [value, label_tooltip]."""
    info_items = [[kind_label, "Tipo"]]
    for k in ("Version", "Description", "Author", "Template"):
        if wp_meta.get(k):
            info_items.append([wp_meta[k], k])
    if rel_path:
        info_items.append([rel_path, "Path"])

    sections = [
        {"label": "Información", "chip_class": "chip-var", "items": info_items},
    ]
    if cpts:
        sections.append({"label": "CPTs", "chip_class": "chip-route",
                         "items": [[s, ""] for s in cpts]})
    if shortcodes:
        sections.append({"label": "Shortcodes", "chip_class": "chip-fn",
                         "items": [[s, ""] for s in shortcodes]})
    return {"sections": sections, "tags": ["activo"]}
