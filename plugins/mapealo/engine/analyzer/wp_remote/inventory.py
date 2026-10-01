"""
Wrappers de WP-CLI para inventariar un sitio WordPress remoto.

Cada función devuelve estructuras normalizadas (lista de dicts o lista de
strings) que el builder consume sin saber de WP-CLI.

Si una llamada falla, propagamos WPRemoteError — no enmascaramos.
"""
from analyzer.wp_remote.ssh import run_wp_cli


def list_plugins(cfg: dict) -> list:
    """
    Retorna [{"name", "title", "status", "version", "update"}].
    `status` ∈ {"active", "inactive", "must-use", "active-network", "dropin"}.
    """
    raw = run_wp_cli(cfg, ["plugin", "list", "--fields=name,title,status,version,update"])
    return [
        {
            "name":    p.get("name", ""),
            "title":   p.get("title", "") or p.get("name", ""),
            "status":  p.get("status", "inactive"),
            "version": p.get("version", ""),
            "update":  p.get("update", "none"),
        }
        for p in raw
    ]


def list_themes(cfg: dict) -> list:
    """
    Retorna [{"name", "title", "status", "version", "template"}].
    `status` ∈ {"active", "inactive", "parent"}.
    Nota: `template` no es un field de `wp theme list`; se infiere `status==parent`.
    """
    raw = run_wp_cli(cfg, ["theme", "list", "--fields=name,title,status,version"])
    return [
        {
            "name":     t.get("name", ""),
            "title":    t.get("title", "") or t.get("name", ""),
            "status":   t.get("status", "inactive"),
            "version":  t.get("version", ""),
            "template": "",   # TODO v1.5.1: `wp theme get <name> --field=template`
        }
        for t in raw
    ]


def list_post_types(cfg: dict) -> list:
    """
    Retorna [{"name", "label", "public", "hierarchical"}].
    Filtra los core para que el grafo no quede ahogado:
    devuelve solo los `public != core` y los explícitamente custom.
    """
    raw = run_wp_cli(cfg, ["post-type", "list", "--fields=name,label,public,hierarchical"])
    core = {"post", "page", "attachment", "revision", "nav_menu_item",
            "custom_css", "customize_changeset", "oembed_cache",
            "user_request", "wp_block", "wp_template", "wp_template_part",
            "wp_global_styles", "wp_navigation",
            "wp_font_family", "wp_font_face"}  # WP 6.5+
    return [
        {
            "name":         pt.get("name", ""),
            "label":        pt.get("label", ""),
            "public":       _truthy(pt.get("public")),
            "hierarchical": _truthy(pt.get("hierarchical")),
        }
        for pt in raw
        if pt.get("name") and pt["name"] not in core
    ]


def list_taxonomies(cfg: dict) -> list:
    """
    Retorna [{"name", "label", "object_type", "hierarchical"}].
    Filtra core (category, post_tag, etc.).
    """
    raw = run_wp_cli(cfg, ["taxonomy", "list", "--fields=name,label,object_type,hierarchical"])
    core = {"category", "post_tag", "nav_menu", "link_category",
            "post_format", "wp_theme", "wp_template_part_area",
            "wp_pattern_category"}
    out: list = []
    for t in raw:
        name = t.get("name", "")
        if not name or name in core:
            continue
        obj = t.get("object_type", "")
        # WP-CLI puede devolver lista o string ("post,page" o ["post"])
        if isinstance(obj, list):
            object_types = obj
        elif isinstance(obj, str):
            object_types = [s.strip() for s in obj.split(",") if s.strip()]
        else:
            object_types = []
        out.append({
            "name":         name,
            "label":        t.get("label", ""),
            "object_types": object_types,
            "hierarchical": _truthy(t.get("hierarchical")),
        })
    return out


def get_active_plugins(cfg: dict) -> set:
    """Set con `name` (slug) de los plugins en estado active o must-use."""
    return {p["name"] for p in list_plugins(cfg) if p["status"] in {"active", "must-use", "active-network"}}


def _truthy(v) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.lower() in {"1", "true", "yes"}
    if isinstance(v, int):
        return v != 0
    return False
