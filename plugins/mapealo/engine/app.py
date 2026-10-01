"""jarvis-map — servidor FastAPI en puerto 17433."""
import json
import re
import shutil
import subprocess
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import paths
import puente
from analyzer import detect_kind
from version import TOOL_VERSION

app = FastAPI(title="jarvis-map", version="2.0")

_THIS_DIR = Path(__file__).resolve().parent
JMAP_DIR  = ".jarvis-map"

_HEADING    = re.compile(r'^# (.+)$', re.MULTILINE)
_CL_DATE    = re.compile(r'###?\s*(\d{4}-\d{2}-\d{2})')
_APP_ID_RE  = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$')


def _safe_app_dir(app_id: str) -> Path:
    """
    Valida app_id contra allowlist. La regex (`^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$`)
    ya impide path traversal (no permite `/`, ni nombres que empiecen con `.`),
    así que NO resolvemos el path — eso rompería symlinks legítimos a fuera
    de la raíz (ej. orus apunta a /media/op/Container/orus).

    La superficie HTTP acepta solo ids, nunca rutas: la resolución a directorio
    la hace `paths` contra las raíces detectadas.
    """
    if not _APP_ID_RE.match(app_id or "") or app_id.startswith('_'):
        raise HTTPException(400, "app_id inválido")
    candidate = paths.resolve_app_dir(app_id)
    if candidate is None or not candidate.is_dir():
        raise HTTPException(404, f"App '{app_id}' no encontrada")
    return candidate


def _jmap(app_dir: Path) -> Path:
    return app_dir / JMAP_DIR


def _display_name(app_dir: Path) -> str:
    app_md = app_dir / "APP.md"
    if app_md.exists():
        m = _HEADING.search(app_md.read_text(encoding='utf-8'))
        if m:
            return m.group(1).strip()
    return app_dir.name


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def _last_changelog_date(app_dir: Path) -> str | None:
    cl = app_dir / "CHANGELOG.md"
    if not cl.exists():
        return None
    m = _CL_DATE.search(cl.read_text(encoding='utf-8'))
    return m.group(1) if m else None


@app.get("/api/apps")
def list_apps():
    apps = []
    for _id, d in paths.list_apps():
        jmap   = _jmap(d)
        mapped = jmap.exists()
        meta   = _read_json(jmap / "meta.json") if mapped and (jmap / "meta.json").exists() else {}

        stale = False
        if meta:
            cl_date   = _last_changelog_date(d)
            stale_cl  = (cl_date or "") > (meta.get("last_changelog_entry") or "")
            tv        = meta.get("tool_version")
            stale_ver = tv is not None and tv != TOOL_VERSION
            stale     = stale_cl or stale_ver

        # kind: si hay meta usar el grabado; sino inferir vía detect_kind
        # (lee jarvis-map.json si existe). Nunca devolver "unknown" al frontend.
        kind = meta.get("kind")
        if not kind:
            inferred = detect_kind(d)
            kind = inferred if inferred != "unknown" else "python"

        apps.append({
            "id":           d.name,
            "display":      _display_name(d),
            "mapped":       mapped,
            "stale":        stale,
            "depth":        meta.get("depth"),
            "stack":        meta.get("stack"),
            "kind":         kind,
            "modules":      meta.get("modules_count"),
            "tool_version": meta.get("tool_version"),
            "generated_at": meta.get("generated_at"),
            "current_tool": TOOL_VERSION,
        })
    return apps


@app.get("/api/graph")
def get_graph(app: str = Query(...)):
    app_dir = _safe_app_dir(app)

    jmap = _jmap(app_dir)
    if not jmap.exists():
        raise HTTPException(
            404,
            f"Sin mapa para '{app}'. Invocá /jarvis-mapealo {app} para generarlo."
        )

    graph  = _read_json(jmap / "graph.json")
    detail = _read_json(jmap / "detail.json") if (jmap / "detail.json").exists() else {}
    meta   = _read_json(jmap / "meta.json")   if (jmap / "meta.json").exists() else {}

    graph["app"]          = app
    graph["app_display"]  = graph.get("app_display") or _display_name(app_dir)
    graph["map"]          = detail
    graph["meta"]         = meta

    return JSONResponse(content=graph)


@app.get("/api/meta")
def get_meta(app: str = Query(...)):
    app_dir = _safe_app_dir(app)
    jmap    = _jmap(app_dir)
    if not (jmap / "meta.json").exists():
        raise HTTPException(404, "Sin meta para esta app")
    return _read_json(jmap / "meta.json")


@app.post("/api/regenerate")
def regenerate(
    app:   str  = Query(...),
    depth: str  = Query("basico"),
    force: bool = Query(False),
    kind:  str  = Query("auto"),
):
    """Invoca mapealo.generate sobre la app validada."""
    _safe_app_dir(app)
    if depth not in ("basico", "profundo"):
        raise HTTPException(400, "depth inválido (basico|profundo)")
    if kind not in ("auto", "python", "wordpress", "wordpress-remote", "jarvis-agents", "nextjs"):
        raise HTTPException(400, "kind inválido (auto|python|wordpress|wordpress-remote|jarvis-agents|nextjs)")

    from mapealo import generate
    try:
        result = generate(app, depth, force, kind=kind)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if "error" in result:
        raise HTTPException(500, result["error"])
    return result


def _open_allowed_roots() -> list[Path]:
    """Roots donde `/api/open` puede abrir. Derivados, no hardcodeados: en otra
    máquina los directorios de agentes tienen otros nombres."""
    return paths.allowed_open_roots()


def _validate_open_path(raw: str) -> Path:
    """Resuelve y valida que el path esté dentro de la allowlist. No expone el path en el error."""
    if not raw:
        raise HTTPException(400, "path requerido")
    try:
        p = Path(raw).expanduser().resolve(strict=True)
    except (OSError, RuntimeError):
        raise HTTPException(404, "path no encontrado")
    for root in _open_allowed_roots():
        try:
            root_resolved = root.resolve()
        except OSError:
            continue
        if p == root_resolved or p.is_relative_to(root_resolved):
            return p
    raise HTTPException(403, "path fuera de roots permitidos")


@app.post("/api/open")
def open_path(path: str = Query(...)):
    """Abre el path con xdg-open (o open en macOS). Validado contra allowlist."""
    target = _validate_open_path(path)
    opener = shutil.which("xdg-open") or shutil.which("open")
    if not opener:
        raise HTTPException(500, "no hay opener (xdg-open|open) disponible")
    try:
        subprocess.Popen(
            [opener, str(target)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
    except OSError:
        raise HTTPException(500, "no se pudo abrir el archivo")
    return {"ok": True}


# ─── puente hacia la sesión de Claude Code ──────────────────────────────────

class _Registro(BaseModel):
    socket:     str
    session_id: str
    cwd:        str
    app:        str | None = None


class _Envio(BaseModel):
    app:         str
    node:        str
    instruccion: str
    sub:         dict | None = None
    enter:       bool        = False
    session_id:  str | None  = None


@app.post("/api/registrar")
def registrar(reg: _Registro):
    """La skill /navegar dice a qué ventana mandarle lo que se clickee."""
    try:
        dato = puente.registrar(reg.socket, reg.session_id, reg.cwd, reg.app)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "app": dato.get("app")}


@app.get("/api/destino")
def ver_destino():
    """
    Estado del canal, para que el panel muestre la referencia REAL (relativa al
    cwd de la sesión) y avise antes de escribir si el envío va a caer al
    portapapeles.
    """
    dest = puente.destino()
    roots = paths.apps_roots()
    base  = {
        "apps_dir": str(roots[0]) if roots else "",
        "roots":    [str(r) for r in roots],
    }
    if not dest:
        return {**base, "via": "portapapeles", "cwd": None, "app": None}
    return {**base, "via": "kitty", "cwd": dest.get("cwd"), "app": dest.get("app")}


@app.post("/api/enviar")
def enviar(env: _Envio):
    """
    Compone la referencia al componente y la escribe en el prompt de la sesión.

    Sin socket vivo no falla: deja el texto en el portapapeles y lo dice, para
    que el front lo avise en vez de quedar en silencio.
    """
    app_dir = _safe_app_dir(env.app)
    if not (env.instruccion or "").strip():
        raise HTTPException(400, "instrucción vacía")

    jmap = _jmap(app_dir)
    if not (jmap / "graph.json").exists():
        raise HTTPException(404, f"Sin mapa para '{env.app}'")
    graph = _read_json(jmap / "graph.json")

    dest  = puente.destino(env.session_id)
    texto = puente.componer(
        app_dir, graph, env.node, env.sub, env.instruccion,
        cwd=(dest or {}).get("cwd") or puente.cwd_registrado(),
    )

    if dest:
        try:
            puente.enviar(dest["socket"], texto, con_enter=env.enter)
            return {"ok": True, "via": "kitty", "texto": texto}
        except (RuntimeError, OSError, subprocess.SubprocessError):
            pass  # la ventana se murió entre el chequeo y el envío

    if puente.al_portapapeles(texto):
        return {"ok": True, "via": "portapapeles", "texto": texto}
    return JSONResponse(
        status_code=503,
        content={"ok": False, "via": "ninguno", "texto": texto,
                 "detalle": "sin sesión registrada y sin portapapeles"},
    )


app.mount("/", StaticFiles(directory=str(_THIS_DIR / "static"), html=True), name="static")
