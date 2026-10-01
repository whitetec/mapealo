"""
puente.py - canal desde el navegador hacia la sesión de Claude Code.

El navegador manda un clic más una instrucción; acá se resuelve a qué ventana
va, se compone la referencia al componente y se escribe en el prompt de esa
terminal vía el control remoto de kitty.

Por qué kitty y no teclas sintéticas: `kitten @ send-text` entrega el texto por
el canal de control de la terminal. No roba el foco, no depende de que el
gestor de ventanas entregue el primer evento y no se equivoca de ventana.

El texto del usuario SIEMPRE viaja por `--stdin`, que kitty manda literal. Sin
eso, una instrucción que contenga `\\n` se convertiría en un salto de línea.
"""
import ast
import json
import os
import re
import shutil
import stat
import subprocess
import time
from pathlib import Path

REG_DIR  = Path.home() / ".claude" / "navegar"
REG_FILE = REG_DIR / "destino.json"

_SOCK_RE = re.compile(r'^unix:(@?[A-Za-z0-9_./@:{}-]{1,200})$')
_TIMEOUT = 5


# ─── registro de la sesión destino ──────────────────────────────────────────

def registrar(socket: str, session_id: str, cwd: str, app: str | None = None) -> dict:
    """Guarda a qué ventana mandarle. Lo llama la skill /navegar al invocarse."""
    if not socket or not _SOCK_RE.match(socket):
        raise ValueError("socket inválido")
    REG_DIR.mkdir(parents=True, exist_ok=True)
    dato = {
        "socket":     socket,
        "session_id": session_id,
        "cwd":        cwd,
        "app":        app,
        "ts":         time.time(),
    }
    # Identidad del socket, no solo su nombre: si la ventana muere y el pid se
    # reusa, el socket nuevo tiene otro inodo y el envío se rechaza en vez de
    # entrar en la terminal equivocada.
    dato["sock_id"] = _identidad(socket)
    tmp = REG_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(dato, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, REG_FILE)
    return dato


def _identidad(socket: str) -> list | None:
    """
    (inodo, ctime) del socket. Los sockets abstractos no tienen archivo.

    Van los dos a propósito: probado en este equipo, al recrear el socket en la
    misma ruta el inodo se reusa al instante, así que el inodo solo no
    distingue una ventana de la siguiente. Lo que separa las dos es el ctime.
    """
    path = socket.split("unix:", 1)[-1]
    if path.startswith("@"):
        return None
    try:
        st = os.stat(path)
    except OSError:
        return None
    return [st.st_ino, st.st_ctime]


def _socket_vivo(socket: str) -> bool:
    """
    Un socket que existe en disco puede ser de una ventana ya muerta, así que
    además de mirar el inodo se le pide algo a kitty. `ls` está permitido bajo
    allow_remote_control=socket-only (verificado).
    """
    path = socket.split("unix:", 1)[-1]
    if not path.startswith("@"):
        try:
            if not stat.S_ISSOCK(os.stat(path).st_mode):
                return False
        except OSError:
            return False
    kitten = shutil.which("kitten")
    if not kitten:
        return False
    try:
        r = subprocess.run(
            [kitten, "@", "--to", socket, "ls"],
            capture_output=True, timeout=_TIMEOUT,
        )
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def cwd_registrado() -> str | None:
    """
    El cwd del último registro, solo para escribir la ruta de forma relativa.
    Se lee aparte de `destino()` porque sirve incluso cuando el destino se
    rechaza: el texto igual va al portapapeles y conviene que sea legible.
    """
    try:
        return json.loads(REG_FILE.read_text(encoding="utf-8")).get("cwd")
    except (OSError, ValueError):
        return None


def destino(session_id: str | None = None) -> dict | None:
    """
    Devuelve el destino registrado, o None si no sirve.

    El caso peligroso no es el de dos sesiones en paralelo sino el secuencial:
    se cierra la ventana que registró, se abre otra, el pid se reusa y el
    socket viejo pasa el chequeo de vivo. Por eso, si el llamador dice de qué
    sesión es y no coincide con la registrada, se niega en vez de adivinar.
    """
    try:
        dato = json.loads(REG_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if session_id and dato.get("session_id") and dato["session_id"] != session_id:
        return None

    socket = dato.get("socket", "")
    guardada = dato.get("sock_id")
    if guardada is not None and _identidad(socket) != guardada:
        return None   # otra ventana ocupa ese nombre de socket

    if not _socket_vivo(socket):
        return None
    return dato


# ─── composición de la referencia ───────────────────────────────────────────

_DESC_RE = re.compile(r'^(?:Módulo|Modulo)\s+(.+)$')


def _rel_path_de(graph: dict, node_id: str) -> str | None:
    """
    rel_path sale del nodo. Los mapas viejos no lo traen (se agregó después),
    así que se cae al `desc`, que tiene la forma "Módulo analyzer/artifacts.py".
    """
    for child in graph.get("children", []):
        if child.get("id") != node_id:
            continue
        if child.get("rel_path"):
            return child["rel_path"]
        m = _DESC_RE.match((child.get("desc") or "").strip())
        if m:
            return m.group(1).strip()
        return None
    return None


def _rango_de(archivo: Path, sub: dict) -> tuple[int, int] | None:
    """
    Ubica el sub-componente en el archivo REAL, no en el mapa.

    El mapa puede estar stale; el archivo en disco es lo que se va a leer
    después. Resolver acá hace que el rango sea correcto aunque el mapa esté
    viejo, y evita tener que meter números de línea en el analizador.
    """
    nombre = (sub or {}).get("name") or ""
    if not nombre or not archivo.exists():
        return None

    if archivo.suffix == ".py":
        try:
            arbol = ast.parse(archivo.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, ValueError):
            arbol = None
        if arbol is not None:
            buscado = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
            for nodo in ast.walk(arbol):
                if isinstance(nodo, buscado) and nodo.name == nombre:
                    fin = getattr(nodo, "end_lineno", None) or nodo.lineno
                    return nodo.lineno, fin

    if archivo.suffix in (".ts", ".tsx", ".js", ".jsx", ".mjs"):
        rango = _rango_ts(archivo, nombre)
        if rango:
            return rango

    # Para rutas y para archivos que no son Python: primera línea que lo menciona
    try:
        for i, linea in enumerate(archivo.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if nombre in linea:
                return i, i
    except OSError:
        pass
    return None


def _rango_ts(archivo: Path, nombre: str) -> tuple[int, int] | None:
    """
    Declaración de `nombre` en TS/JS y su fin por balance de llaves y paréntesis.

    Sin parser de TS: se busca `function nombre`, `const nombre =`, `class nombre`,
    `type`/`interface`/`enum nombre` o `export async function GET`, y desde ahí se
    cuentan (), {} y [] hasta volver a cero. Se ignoran strings y comentarios de una
    línea; un `{` dentro de un template literal puede correr el fin, por eso hay tope.
    Sin esto, el primer match era casi siempre el `import` del mismo nombre.
    """
    import re
    try:
        lineas = archivo.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    # Bloques de la vista Diseño: `#id` o `/* comentario` ubican una <section> de
    # la página y el rango va hasta su </section>.
    if nombre.startswith("#") or nombre.startswith("/* "):
        return _rango_seccion(lineas, nombre)
    nombre = nombre.split("(")[0].strip()
    if not nombre:
        return None
    decl = re.compile(
        rf"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?"
        rf"(?:function\s*\*?\s*{re.escape(nombre)}\b|(?:const|let|var)\s+{re.escape(nombre)}\b|"
        rf"class\s+{re.escape(nombre)}\b|(?:type|interface|enum)\s+{re.escape(nombre)}\b)"
    )
    ini = next((i for i, l in enumerate(lineas) if decl.search(l)), None)
    if ini is None:
        return None
    prof, abrio = 0, False
    limpio = re.compile(r"""(["'])(?:\\.|(?!\1).)*\1|//.*$""")
    for j in range(ini, min(len(lineas), ini + 600)):
        t = limpio.sub("", lineas[j])
        for ch in t:
            if ch in "({[":
                prof += 1
                abrio = True
            elif ch in ")}]":
                prof -= 1
        if abrio and prof <= 0:
            return ini + 1, j + 1
        if not abrio and t.rstrip().endswith(";"):
            return ini + 1, j + 1
    return ini + 1, ini + 1


def _rango_seccion(lineas: list, nombre: str) -> tuple[int, int] | None:
    import re
    if nombre.startswith("#"):
        marca = re.compile(rf'<section\b[^>]*\bid="{re.escape(nombre[1:])}"')
        ini = next((i for i, l in enumerate(lineas) if marca.search(l)), None)
    else:
        texto = nombre[3:].strip()
        com = next((i for i, l in enumerate(lineas) if "{/*" in l and texto in l), None)
        ini = next((i for i in range(com, len(lineas)) if "<section" in lineas[i]), None) if com is not None else None
    if ini is None:
        return None
    prof = 0
    for j in range(ini, len(lineas)):
        prof += len(re.findall(r"<section\b", lineas[j])) - len(re.findall(r"</section>", lineas[j]))
        if prof <= 0:
            return ini + 1, j + 1
    return ini + 1, ini + 1


def _ruta_para_prompt(archivo: Path, cwd: str | None) -> str:
    """
    La referencia se escribe relativa al cwd de la sesión, que es como Claude
    Code resuelve un `@path`. Si el archivo cae fuera, va absoluta.
    """
    if cwd:
        try:
            return str(archivo.relative_to(Path(cwd)))
        except ValueError:
            pass
    return str(archivo)


def componer(app_dir: Path, graph: dict, node_id: str, sub: dict | None,
             instruccion: str, cwd: str | None = None) -> str:
    """Arma el texto que se va a escribir en el prompt."""
    instruccion = (instruccion or "").strip()

    rel = _rel_path_de(graph, node_id)
    if not rel:
        # Un nodo pilar (o un mapa sin rel_path): se referencia por nombre.
        etiqueta = next(
            (p.get("label") for p in graph.get("pillars", []) if p.get("id") == node_id),
            node_id,
        )
        return f"[{etiqueta}] {instruccion}".strip()

    archivo = app_dir / rel
    ruta    = _ruta_para_prompt(archivo, cwd)

    rango = _rango_de(archivo, sub or {})
    if rango and sub:
        ini, fin = rango
        marca = f"@{ruta}:{ini}-{fin}" if fin > ini else f"@{ruta}:{ini}"
        return f"{marca} ({sub.get('name')}) - {instruccion}".strip()
    return f"@{ruta} - {instruccion}".strip()


# ─── entrega ────────────────────────────────────────────────────────────────

def enviar(socket: str, texto: str, con_enter: bool = False) -> None:
    """
    Escribe el texto en el prompt de la ventana. Con `con_enter`, lo manda.

    Van en dos llamadas a propósito: el texto literal por --stdin, y el retorno
    aparte. Así un clic de más deja algo editable en el prompt en vez de
    disparar un turno.
    """
    kitten = shutil.which("kitten")
    if not kitten:
        raise RuntimeError("kitten no disponible")

    base = [kitten, "@", "--to", socket, "send-text", "--stdin"]
    r = subprocess.run(base, input=texto.encode("utf-8"),
                       capture_output=True, timeout=_TIMEOUT)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode("utf-8", "replace").strip() or "send-text falló")

    if con_enter:
        r = subprocess.run(base, input=b"\r", capture_output=True, timeout=_TIMEOUT)
        if r.returncode != 0:
            raise RuntimeError("no se pudo mandar el retorno")


def al_portapapeles(texto: str) -> bool:
    """
    Respaldo cuando no hay socket: queda listo para pegar con Ctrl+Shift+V.

    xclip se queda vivo en segundo plano reteniendo la selección, así que no se
    lo puede esperar con capture_output: heredaría los pipes y el wait colgaría
    hasta el timeout. Se le cierran las salidas y solo se espera a que tome el
    texto por stdin.
    """
    xclip = shutil.which("xclip")
    if not xclip:
        return False
    try:
        proc = subprocess.Popen(
            [xclip, "-selection", "clipboard"],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
        proc.stdin.write(texto.encode("utf-8"))
        proc.stdin.close()
        return True
    except (OSError, subprocess.SubprocessError):
        return False
