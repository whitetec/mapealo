"""Autodetección del ecosistema de agentes.

El kind `jarvis-agents` nació leyendo las fichas de `~/jarvis-director/agentes/`.
Esa es una convención del autor y no existe en otra máquina. Acá el ecosistema
se descubre por las convenciones de Claude Code, que sí son universales:

    <claude_home>/agents/*.md        subagentes (frontmatter name/description)
    <claude_home>/skills/**/SKILL.md skills (incluye las sincronizadas)
    <claude_home>/commands/**/*.md   slash commands
    <claude_home>/plugins/           plugins instalados y las skills que traen
    <claude_home>/settings.json      hooks
    ~/.claude.json                   MCP servers de scope usuario
    <proyecto>/.claude/...           lo mismo con scope de proyecto
    <proyecto>/.mcp.json             MCP servers de scope proyecto
    <dir>/CLAUDE.md                  un directorio con CLAUDE.md es un agente

Las fichas del operador, si están, se suman y ganan: traen taxonomía propia
(Tipo, Capability, Autonomy) que ninguna convención estándar expresa.
"""
import json
import os
import re
from pathlib import Path

import paths

# Pilares genéricos: la fuente de la que viene cada componente.
P_AGENT   = "agent"
P_SKILL   = "skill"
P_COMMAND = "command"
P_PLUGIN  = "plugin"
P_MCP     = "mcp"
P_HOOK    = "hook"

# Topes: un ecosistema grande no debe colgar el mapeo ni el layout.
_MAX_COMPONENTS = 500
_MAX_READ       = 40_000   # bytes por archivo al buscar referencias cruzadas
_MAX_DESC       = 240

_FM_DELIM = re.compile(r'^---\s*$')
_FM_KEY   = re.compile(r'^([A-Za-z_][A-Za-z0-9_-]*)\s*:\s*(.*)$')
_H1       = re.compile(r'^#\s+(.+)$', re.MULTILINE)


def read_frontmatter(path: Path) -> tuple[dict, str]:
    """Devuelve (frontmatter, cuerpo). Parser mínimo: `clave: valor` planos.

    No usamos PyYAML a propósito: el tool no tiene más dependencias que
    fastapi y uvicorn, y los frontmatter de Claude Code son planos.
    """
    try:
        text = path.read_text(encoding='utf-8', errors='replace')[:_MAX_READ]
    except OSError:
        return {}, ""
    lines = text.splitlines()
    if not lines or not _FM_DELIM.match(lines[0]):
        return {}, text
    fm: dict = {}
    end = len(lines)
    for i, line in enumerate(lines[1:], start=1):
        if _FM_DELIM.match(line):
            end = i
            break
        m = _FM_KEY.match(line)
        if m:
            val = m.group(2).strip().strip('"').strip("'")
            fm[m.group(1).lower()] = val
    return fm, "\n".join(lines[end + 1:])


def _clip(s: str) -> str:
    s = " ".join((s or "").split())
    return s if len(s) <= _MAX_DESC else s[:_MAX_DESC - 1] + "…"


def _comp(cid, label, pillar, *, desc="", path="", scope="", tags=None, items=None) -> dict:
    return {
        "id":     cid,
        "label":  label,
        "pillar": pillar,
        "desc":   _clip(desc),
        "path":   str(path or ""),
        "scope":  scope,
        "tags":   tags or [],
        "items":  items or [],
    }


# ─── scanners por convención ────────────────────────────────────────────────

def scan_agents_md(cc_dir: Path, scope: str) -> list[dict]:
    """`<.claude>/agents/*.md` — subagentes nativos de Claude Code."""
    d = cc_dir / "agents"
    if not d.is_dir():
        return []
    out = []
    for md in sorted(d.rglob("*.md")):
        fm, body = read_frontmatter(md)
        name = fm.get("name") or md.stem
        items = [[v, k.capitalize()] for k, v in (
            ("model", fm.get("model")), ("tools", fm.get("tools")),
        ) if v]
        items.append([scope, "Scope"])
        items.append([str(md), "Definición", str(md)])
        out.append(_comp(
            name, name, P_AGENT,
            desc=fm.get("description") or _first_heading(body),
            path=md, scope=scope, tags=["subagente", scope.split(':')[0]],
            items=items,
        ))
    return out


def scan_skills(cc_dir: Path, scope: str) -> list[dict]:
    """`<.claude>/skills/**/SKILL.md`. Cubre las sincronizadas, que viven un
    nivel más abajo dentro de un directorio-bucket con nombre de uuid."""
    d = cc_dir / "skills"
    if not d.is_dir():
        return []
    out = []
    for sk in sorted(d.rglob("SKILL.md")):
        fm, body = read_frontmatter(sk)
        name = fm.get("name") or sk.parent.name
        synced = "synced" in sk.parts
        out.append(_comp(
            name, name, P_SKILL,
            desc=fm.get("description") or _first_heading(body),
            path=sk, scope=scope,
            tags=["skill"] + (["sincronizada"] if synced else []) + [scope.split(':')[0]],
            items=[
                [scope, "Scope"],
                ["sincronizada" if synced else "local", "Origen"],
                [str(sk), "SKILL.md", str(sk)],
            ],
        ))
    return out


def scan_commands(cc_dir: Path, scope: str) -> list[dict]:
    """`<.claude>/commands/**/*.md` — slash commands."""
    d = cc_dir / "commands"
    if not d.is_dir():
        return []
    out = []
    for md in sorted(d.rglob("*.md")):
        fm, body = read_frontmatter(md)
        rel  = md.relative_to(d).with_suffix("")
        name = "/" + str(rel).replace(os.sep, ":")
        out.append(_comp(
            name, name, P_COMMAND,
            desc=fm.get("description") or _first_heading(body),
            path=md, scope=scope, tags=["comando", scope.split(':')[0]],
            items=[[scope, "Scope"], [str(md), "Definición", str(md)]],
        ))
    return out


def scan_plugins(cc_home: Path) -> list[dict]:
    """`plugins/installed_plugins.json` + las skills que trae cada plugin."""
    reg = cc_home / "plugins/installed_plugins.json"
    try:
        data = json.loads(reg.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return []
    out = []
    for full_name, installs in (data.get("plugins") or {}).items():
        if not isinstance(installs, list) or not installs:
            continue
        name   = full_name.split('@')[0]
        market = full_name.split('@')[1] if '@' in full_name else ""
        scopes = sorted({i.get("scope", "?") for i in installs if isinstance(i, dict)})
        install_path = next(
            (i.get("installPath") for i in installs
             if isinstance(i, dict) and i.get("installPath")), ""
        )
        desc = ""
        if install_path:
            try:
                pj = json.loads(
                    (Path(install_path) / ".claude-plugin/plugin.json")
                    .read_text(encoding='utf-8')
                )
                desc = pj.get("description", "")
            except (OSError, json.JSONDecodeError):
                pass
        out.append(_comp(
            name, name, P_PLUGIN, desc=desc, path=install_path,
            scope="plugin", tags=["plugin"] + scopes,
            items=[
                [market or "local", "Marketplace"],
                [", ".join(scopes), "Scope"],
                [str(len(installs)), "Instalaciones"],
            ] + ([[install_path, "Directorio", install_path]] if install_path else []),
        ))
        # Las skills del plugin son componentes propios, atribuidas al plugin.
        if install_path:
            for sk in sorted(Path(install_path).rglob("skills/*/SKILL.md")):
                fm, body = read_frontmatter(sk)
                sname = fm.get("name") or sk.parent.name
                out.append(_comp(
                    sname, sname, P_SKILL,
                    desc=fm.get("description") or _first_heading(body),
                    path=sk, scope=f"plugin:{name}",
                    tags=["skill", "plugin"],
                    items=[
                        [name, "Plugin"],
                        [str(sk), "SKILL.md", str(sk)],
                    ],
                ))
    return out


def scan_mcp(cc_home: Path, project_dirs: list[Path]) -> list[dict]:
    """MCP servers de scope usuario (`~/.claude.json`, `settings.json`) y de
    proyecto (`<proyecto>/.mcp.json`)."""
    found: dict[str, dict] = {}

    def absorb(servers: dict, scope: str):
        if not isinstance(servers, dict):
            return
        for name, spec in servers.items():
            if name in found:
                continue
            spec = spec if isinstance(spec, dict) else {}
            transport = spec.get("type") or ("http" if spec.get("url") else "stdio")
            cmd = spec.get("command") or spec.get("url") or ""
            found[name] = _comp(
                name, name, P_MCP,
                desc=f"MCP {transport}" + (f" · {cmd}" if cmd else ""),
                scope=scope, tags=["mcp", transport],
                items=[[scope, "Scope"], [transport, "Transporte"]]
                      + ([[cmd, "Comando"]] if cmd else []),
            )

    for f, scope in ((Path.home() / ".claude.json", "usuario"),
                     (cc_home / "settings.json", "usuario")):
        try:
            absorb(json.loads(f.read_text(encoding='utf-8')).get("mcpServers") or {}, scope)
        except (OSError, json.JSONDecodeError):
            continue
    for pd in project_dirs:
        try:
            absorb(
                json.loads((pd / ".mcp.json").read_text(encoding='utf-8')).get("mcpServers") or {},
                f"proyecto:{pd.name}",
            )
        except (OSError, json.JSONDecodeError):
            continue
    return list(found.values())


def scan_hooks(cc_home: Path) -> list[dict]:
    """Eventos con hooks configurados en `settings.json`. Un componente por
    evento, no por comando: el evento es la unidad que se razona."""
    try:
        cfg = json.loads((cc_home / "settings.json").read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return []
    hooks = cfg.get("hooks") or {}
    if not isinstance(hooks, dict):
        return []
    out = []
    for event, matchers in hooks.items():
        n = len(matchers) if isinstance(matchers, list) else 1
        out.append(_comp(
            f"hook:{event}", event, P_HOOK,
            desc=f"{n} matcher(s) configurado(s)",
            scope="usuario", tags=["hook"],
            items=[[event, "Evento"], [str(n), "Matchers"]],
        ))
    return out


def scan_claude_md_dirs(dirs: list[Path]) -> list[dict]:
    """Directorios con `CLAUDE.md` propio. En un setup multi-agente cada uno es
    un agente; en uno normal son los proyectos con instrucciones.

    Recibe la lista ya armada en vez de un home: los proyectos del operador
    pueden estar en el home (`~/jarvis-dev`) o un nivel más abajo
    (`~/src/api-gateway`), y las dos formas cuentan igual.
    """
    out = []
    for d in dirs:
        if not d.is_dir() or d.name.startswith('.'):
            continue
        cmd_file = d / "CLAUDE.md"
        if not cmd_file.is_file():
            continue
        try:
            text = cmd_file.read_text(encoding='utf-8', errors='replace')[:_MAX_READ]
        except OSError:
            continue
        m = _H1.search(text)
        out.append(_comp(
            d.name, d.name, P_AGENT,
            desc=m.group(1).strip() if m else "",
            path=d, scope="directorio", tags=["agente", "claude-md"],
            items=[
                [str(d), "Directorio", str(d)],
                [str(cmd_file), "CLAUDE.md", str(cmd_file)],
            ],
        ))
    return out


def _first_heading(body: str) -> str:
    m = _H1.search(body or "")
    return m.group(1).strip() if m else ""


# ─── composición ────────────────────────────────────────────────────────────

def _project_dirs(limit: int = 40) -> list[Path]:
    """Proyectos donde buscar config de scope proyecto: las apps conocidas
    más los directorios del home que tengan `.claude/` o `CLAUDE.md`."""
    dirs: list[Path] = [p for _, p in paths.list_apps()]
    home = Path.home()
    try:
        for d in sorted(home.iterdir()):
            if d.is_dir() and not d.name.startswith('.') and (
                (d / ".claude").is_dir() or (d / "CLAUDE.md").is_file()
            ):
                dirs.append(d)
    except OSError:
        pass
    out: list[Path] = []
    for d in dirs:
        if d not in out:
            out.append(d)
    return out[:limit]


def detect_ecosystem(cfg: dict | None = None) -> dict:
    """Descubre el ecosistema completo.

    Retorna {"components": [...], "sources": {...}} donde cada componente ya
    trae pilar, descripción y filas de detalle. `sources` documenta de dónde
    salió cada cosa, para que el mapa sea auditable en otra máquina.
    """
    cfg      = cfg or {}
    cc_home  = paths.claude_home()
    home     = Path.home()
    projects = _project_dirs()

    comps: list[dict] = []
    sources: dict     = {"claude_home": str(cc_home), "projects_scanned": len(projects)}

    comps += scan_agents_md(cc_home, "usuario")
    comps += scan_skills(cc_home, "usuario")
    comps += scan_commands(cc_home, "usuario")
    comps += scan_plugins(cc_home)
    comps += scan_mcp(cc_home, projects)
    comps += scan_hooks(cc_home)

    for pd in projects:
        cc = pd / ".claude"
        if not cc.is_dir():
            continue
        scope = f"proyecto:{pd.name}"
        comps += scan_agents_md(cc, scope)
        comps += scan_skills(cc, scope)
        comps += scan_commands(cc, scope)

    # Candidatos a agente: los hijos directos del home más los proyectos ya
    # conocidos, que pueden estar a más de un nivel.
    try:
        home_children = [d for d in sorted(home.iterdir()) if d.is_dir()]
    except OSError:
        home_children = []
    comps += scan_claude_md_dirs(_dedup_paths(home_children + projects))

    sources["found_by_pillar"] = _count_by_pillar(comps)
    comps = _dedup(comps)
    if len(comps) > _MAX_COMPONENTS:
        sources["truncated_at"] = _MAX_COMPONENTS
        comps = comps[:_MAX_COMPONENTS]
    return {"components": comps, "sources": sources}


def _dedup_paths(dirs: list[Path]) -> list[Path]:
    out: list[Path] = []
    for d in dirs:
        if d not in out:
            out.append(d)
    return out


def _count_by_pillar(comps: list[dict]) -> dict:
    out: dict = {}
    for c in comps:
        out[c["pillar"]] = out.get(c["pillar"], 0) + 1
    return out


# Prioridad de fuente ante ids iguales: lo más específico gana.
_SCOPE_RANK = {"directorio": 0, "usuario": 3, "plugin": 2}


def _dedup(comps: list[dict]) -> list[dict]:
    """Un mismo nombre puede aparecer por dos fuentes (un dir con CLAUDE.md y
    su ficha, una skill de usuario y la del plugin). Gana la más informativa."""
    by_id: dict[str, dict] = {}
    for c in comps:
        key  = f"{c['pillar']}:{c['id']}"
        prev = by_id.get(key)
        if prev is None:
            by_id[key] = c
            continue
        if _rank(c) > _rank(prev):
            merged = dict(c)
            merged["items"] = c["items"] + [
                it for it in prev["items"] if it not in c["items"]
            ]
            merged["tags"] = sorted(set(c["tags"]) | set(prev["tags"]))
            by_id[key] = merged
        else:
            prev["tags"] = sorted(set(prev["tags"]) | set(c["tags"]))
            prev["items"] += [it for it in c["items"] if it not in prev["items"]]
    return list(by_id.values())


def _rank(c: dict) -> int:
    base = _SCOPE_RANK.get(c["scope"].split(':')[0], 4)
    return base * 10 + (1 if c["desc"] else 0)
