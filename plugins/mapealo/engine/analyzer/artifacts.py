"""Detecta artefactos (archivos/dirs generados o leídos) por módulo via AST."""
import ast
import re
from pathlib import Path


IMAGE_EXTS    = {'.jpg', '.jpeg', '.png', '.tiff', '.tif', '.gif', '.bmp', '.webp'}
DOC_EXTS      = {'.pdf', '.docx', '.doc', '.odt'}
DATA_EXTS     = {'.json', '.csv', '.xml', '.html', '.txt', '.tsv', '.yaml', '.yml', '.npy'}
DB_EXTS       = {'.db', '.sqlite', '.sqlite3'}
WRITE_MODES   = {'w', 'wb', 'a', 'ab', 'x', 'xb', 'wt'}

WRITE_METHODS = {'save', 'imwrite', 'write_text', 'write_bytes', 'dump', 'savetxt'}
COPY_METHODS  = {'copy', 'copy2', 'copyfile', 'move', 'copytree'}


def artifact_type(path: str) -> str:
    p = path.lower().rstrip('/')
    ext = Path(p).suffix
    if ext in IMAGE_EXTS:   return 'image'
    if ext in DOC_EXTS:     return 'document'
    if ext in DATA_EXTS:    return 'data'
    if ext in DB_EXTS:      return 'database'
    if not ext or path.endswith('/'):
        return 'directory'
    return 'file'


def _str(node) -> str | None:
    """Extrae string literal o prefijo estático de f-string."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts = []
        for v in node.values:
            if isinstance(v, ast.Constant) and isinstance(v.value, str):
                parts.append(v.value)
            else:
                break
        return ''.join(parts) or None
    return None


def _path_hint(node) -> str | None:
    """Extrae pista de ruta (o patrón de extensión) desde cualquier expresión."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        v = node.value
        if '/' in v or '\\' in v or re.search(r'\.\w{2,5}$', v):
            return v
        return None
    if isinstance(node, ast.JoinedStr):
        # Buscar partes constantes — el sufijo puede ser una extensión
        consts = [v.value for v in node.values
                  if isinstance(v, ast.Constant) and isinstance(v.value, str)]
        static = ''.join(consts)
        m = re.search(r'(\.\w{2,5})$', static)
        if m:
            return '*' + m.group(1)  # e.g., "*.json"
        return None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        # Path / expr  (pathlib division)
        return _path_hint(node.right) or _path_hint(node.left)
    if isinstance(node, ast.Call):
        fname = getattr(node.func, 'id', None) or getattr(node.func, 'attr', None)
        if fname in ('str', 'Path') and node.args:
            return _path_hint(node.args[0])
        if fname == 'join' and node.args:
            return _path_hint(node.args[-1])
    return None


def detect_artifacts(pyfile: Path) -> list:
    """
    Retorna [{'op': 'write'|'read', 'path_hint': str, 'artifact_type': str}].
    path_hint puede ser ruta exacta, prefijo de directorio, patrón *.ext, etc.
    """
    src = pyfile.read_text(errors='ignore')
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []

    # ── Constantes ALL_CAPS de nivel módulo que parecen paths ──
    path_consts: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id.isupper():
                    val = _str(node.value)
                    if val and ('/' in val or '\\' in val or re.search(r'\.\w{2,5}$', val)):
                        path_consts[t.id] = val

    # ── Variables locales con pistas de ruta (asignaciones dentro de funciones) ──
    local_hints: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and not t.id.isupper():
                    hint = _path_hint(node.value)
                    if hint:
                        local_hints[t.id] = hint

    results: list[dict] = []
    seen: set[tuple] = set()

    def add(op: str, raw_hint: str):
        if not raw_hint or len(raw_hint) < 2:
            return
        hint = raw_hint.strip().replace('\\', '/')
        key = (op, hint)
        if key in seen:
            return
        seen.add(key)
        results.append({'op': op, 'path_hint': hint, 'artifact_type': artifact_type(hint)})

    def resolve(node) -> str | None:
        """Intenta obtener string de nodo, incluyendo variables y str() wrappers."""
        s = _str(node)
        if s:
            return s
        if isinstance(node, ast.Name):
            return path_consts.get(node.id) or local_hints.get(node.id)
        if isinstance(node, ast.Call):
            fname = getattr(node.func, 'id', None) or getattr(node.func, 'attr', None)
            if fname in ('str', 'Path') and node.args:
                return resolve(node.args[0])
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            return None
        return None

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func

        func_name = (
            getattr(func, 'id', None) or
            getattr(func, 'attr', None)
        )

        # open(path, mode)
        if func_name == 'open' and node.args:
            path_str = resolve(node.args[0])
            mode = 'r'
            if len(node.args) >= 2:
                m = _str(node.args[1])
                if m: mode = m
            for kw in node.keywords:
                if kw.arg == 'mode':
                    m = _str(kw.value)
                    if m: mode = m
            if path_str:
                op = 'write' if mode and mode[0] in ('w', 'a', 'x') else 'read'
                add(op, path_str)

        # image.save(path) / cv2.imwrite(path, img) / np.save(path) / np.savetxt(path)
        elif func_name in ('save', 'imwrite', 'savetxt') and node.args:
            path_str = resolve(node.args[0])
            if path_str:
                add('write', path_str)

        # pathlib: path.write_text / write_bytes
        elif func_name in ('write_text', 'write_bytes'):
            if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
                varname = func.value.id
                val = path_consts.get(varname) or local_hints.get(varname)
                if val:
                    add('write', val)

        # shutil.copy / copy2 / move / copyfile / copytree
        elif func_name in COPY_METHODS and len(node.args) >= 2:
            dst = resolve(node.args[1])
            if dst:
                add('write', dst)
            src_arg = resolve(node.args[0])
            if src_arg:
                add('read', src_arg)

        # os.makedirs(path) / path.mkdir()
        elif func_name in ('makedirs', 'mkdir'):
            path_str = None
            if node.args:
                path_str = resolve(node.args[0])
            elif isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
                varname = func.value.id
                path_str = path_consts.get(varname) or local_hints.get(varname)
            if path_str:
                add('write', path_str if path_str.endswith('/') else path_str + '/')

    # Constantes ALL_CAPS con keywords de salida/entrada que no fueron capturadas
    for name, val in path_consts.items():
        if any(k in name for k in ('OUTPUT', 'OUT_', 'DEST', 'TARGET', 'EXPORT', 'SAVE', 'WRITE')):
            add('write', val)
        elif any(k in name for k in ('INPUT', 'IN_', 'SOURCE', 'SRC', 'READ')):
            add('read', val)

    return results
