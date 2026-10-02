"""
Analyzer WordPress remoto — entry point: generate_wp_remote(app_dir, depth, app_display).

Combina:
  - Inventario remoto vía WP-CLI/SSH (plugins, themes, CPTs, taxonomías)
  - Parser PHP local (analyzer.wp.parser) sobre dirs declarados en
    `local_php_dirs` del mapealo.json — útil para mapear mu-plugins
    que viven en el repo del agente sin tocar el VPS.
"""
from pathlib import Path

from analyzer            import load_config
from analyzer.wp.builder import build_wp_graph
from analyzer.wp.parser  import parse_php_components
from analyzer.wp_remote.inventory import (
    list_plugins, list_themes, list_post_types, list_taxonomies,
)


def generate_wp_remote(app_dir: Path, depth: str, app_display: str) -> tuple:
    """
    Pipeline WordPress remoto.

    depth basico:    plugins, themes, CPTs, taxonomías + parser PHP local
    depth profundo:  + edges contenido → owner cuando se puede inferir

    Retorna (graph, detail, stack, components_count).
    """
    cfg = load_config(app_dir)

    plugins      = list_plugins(cfg)
    themes       = list_themes(cfg)
    post_types   = list_post_types(cfg)
    taxonomies   = list_taxonomies(cfg)

    components: list = []
    detail: dict     = {}

    # ── Plugins ────────────────────────────────────────────────────────────
    for p in plugins:
        cid = f"plugin:{p['name']}"
        components.append({
            "id":     cid, "pillar": "plugins",
            "label":  p["title"], "rel_path": p["name"],
            "tags":   _plugin_tags(p),
        })
        detail[cid] = _plugin_detail(p)

    # ── Themes ─────────────────────────────────────────────────────────────
    for t in themes:
        cid = f"theme:{t['name']}"
        components.append({
            "id":     cid, "pillar": "theme",
            "label":  t["title"], "rel_path": t["name"],
            "tags":   _theme_tags(t),
        })
        detail[cid] = _theme_detail(t)

    # ── Contenido: CPTs ────────────────────────────────────────────────────
    for pt in post_types:
        cid = f"cpt:{pt['name']}"
        components.append({
            "id":     cid, "pillar": "contenido",
            "label":  pt["label"] or pt["name"], "rel_path": "",
            "tags":   ["public"] if pt["public"] else ["private"],
        })
        detail[cid] = _section_set([
            ("Tipo", "chip-parent", [["Custom Post Type", ""]]),
            ("Slug", "chip-var",    [[pt["name"], "Slug"]]),
            ("Hierarchical", "chip-var",
             [["sí" if pt["hierarchical"] else "no", "Hierarchical"]]),
        ])

    # ── Contenido: taxonomías ──────────────────────────────────────────────
    for tx in taxonomies:
        cid = f"tax:{tx['name']}"
        components.append({
            "id":     cid, "pillar": "contenido",
            "label":  tx["label"] or tx["name"], "rel_path": "",
            "tags":   ["taxonomy"],
        })
        items_obj = [[ot, ""] for ot in tx["object_types"]] or [["(global)", ""]]
        detail[cid] = _section_set([
            ("Tipo", "chip-parent", [["Taxonomía", ""]]),
            ("Slug", "chip-var",    [[tx["name"], "Slug"]]),
            ("Aplica a", "chip-route", items_obj),
            ("Hierarchical", "chip-var",
             [["sí" if tx["hierarchical"] else "no", "Hierarchical"]]),
        ])

    # ── Local PHP (mu-plugins, etc.) ───────────────────────────────────────
    local_findings = _scan_local_php(app_dir, cfg)
    for slug in local_findings["cpts"]:
        cid = f"cpt:{slug}"
        if cid not in detail:
            components.append({
                "id":     cid, "pillar": "contenido",
                "label":  slug, "rel_path": "(local php)",
                "tags":   ["cpt", "local-only"],
            })
            detail[cid] = _section_set([
                ("Tipo", "chip-parent", [["CPT (local-only)", ""]]),
                ("Slug", "chip-var",    [[slug, ""]]),
            ])
    for tag in local_findings["shortcodes"]:
        cid = f"shortcode:{tag}"
        if cid not in detail:
            components.append({
                "id":     cid, "pillar": "contenido",
                "label":  f"[{tag}]", "rel_path": "(local php)",
                "tags":   ["shortcode", "local-only"],
            })
            detail[cid] = _section_set([
                ("Tipo", "chip-parent", [["Shortcode (local-only)", ""]]),
            ])

    # ── Pillar map ────────────────────────────────────────────────────────
    pillar_map = {c["id"]: c["pillar"] for c in components}

    # ── Dep edges (depth profundo) ────────────────────────────────────────
    dep_edges: list = []
    if depth == "profundo":
        # CPT/taxonomía → plugin/theme que se asume lo registra: si el slug
        # del CPT coincide con un plugin/theme name, lo enlazamos. No es
        # autoritativo (en general no podemos saberlo sin AST PHP), pero da
        # una pista visual razonable.
        comp_ids = {c["id"] for c in components}
        for c in components:
            if c["pillar"] != "contenido":
                continue
            slug = c["id"].split(":", 1)[1]
            for owner_kind in ("plugin", "theme"):
                cand = f"{owner_kind}:{slug}"
                if cand in comp_ids:
                    dep_edges.append({"source": c["id"], "target": cand})
                    break

    graph = build_wp_graph(components, pillar_map, dep_edges, app_display)
    graph["artifacts"] = []
    return graph, detail, "wordpress-remote", len(components)


# ── Detail builders ────────────────────────────────────────────────────────

def _plugin_tags(p: dict) -> list:
    tags = [p["status"]]
    if p["update"] and p["update"] != "none":
        tags.append("update-available")
    return tags


def _plugin_detail(p: dict) -> dict:
    # Pair [value, label] — value visible en chip, label como tooltip
    info = [[p["status"], "Estado"], [p["version"], "Versión"]]
    if p["update"] and p["update"] != "none":
        info.append([p["update"], "Update disponible"])
    info.append([p["name"], "Slug"])
    return _section_set([("Información", "chip-var", info)])


def _theme_tags(t: dict) -> list:
    tags = [t["status"]]
    if t.get("template"):
        tags.append("child")
    return tags


def _theme_detail(t: dict) -> dict:
    info = [[t["status"], "Estado"], [t["version"], "Versión"]]
    if t.get("template"):
        info.append([t["template"], "Template (parent)"])
    info.append([t["name"], "Slug"])
    return _section_set([("Información", "chip-var", info)])


def _section_set(triples: list) -> dict:
    return {
        "tags": ["activo"],
        "sections": [
            {"label": label, "chip_class": cls, "items": items}
            for (label, cls, items) in triples
        ],
    }


def _scan_local_php(app_dir: Path, cfg: dict) -> dict:
    """Parsea los local_php_dirs del config. Default: ['mu-plugins']."""
    dirs = cfg.get("local_php_dirs") or ["mu-plugins"]
    agg  = {"cpts": set(), "shortcodes": set()}
    for rel in dirs:
        d = app_dir / rel
        if not d.is_dir():
            continue
        result = parse_php_components(d)
        agg["cpts"].update(result.get("cpts", []))
        agg["shortcodes"].update(result.get("shortcodes", []))
    return {k: sorted(v) for k, v in agg.items()}
