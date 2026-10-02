"""
Runner de WP-CLI sobre SSH para sitios WordPress remotos.

Uso:
    cfg = {
        "ssh": {
            "host": "1.2.3.4", "user": "deploy", "key": "~/.ssh/key",
            "port": 22, "wp_path": "/var/www/site/"
        }
    }
    posts = run_wp_cli(cfg, ["post", "list", "--post_type=page"])

Errores se levantan como WPRemoteError con detalle del comando que falló,
para que el caller pueda reportarlos al usuario sin enmascarar la causa.
"""
import json
import shlex
import subprocess
from pathlib import Path


DEFAULT_TIMEOUT = 30


class WPRemoteError(RuntimeError):
    """SSH falló, wp no encontrado, JSON inválido, etc."""


def _expand(p: str) -> str:
    return str(Path(p).expanduser()) if p else p


def _build_ssh_cmd(ssh_cfg: dict, wp_args: list) -> list:
    """
    Construye el argv completo para subprocess. wp_args ya viene tal cual
    se pasaría a `wp` (sin el `wp` inicial). El comando final es:
        ssh [-i KEY] [-p PORT] USER@HOST "wp --path=PATH ARG1 ARG2 ..."
    """
    required = ("host", "user", "wp_path")
    missing  = [k for k in required if not ssh_cfg.get(k)]
    if missing:
        raise WPRemoteError(f"ssh.{missing[0]} faltante en mapealo.json")

    ssh_argv = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
                "-o", "StrictHostKeyChecking=accept-new"]
    if ssh_cfg.get("key"):
        ssh_argv += ["-i", _expand(ssh_cfg["key"])]
    if ssh_cfg.get("port"):
        ssh_argv += ["-p", str(ssh_cfg["port"])]
    ssh_argv.append(f"{ssh_cfg['user']}@{ssh_cfg['host']}")

    # Comando remoto: lo armamos como una sola string shell-escaped
    remote_cmd = ["wp", f"--path={ssh_cfg['wp_path']}", *wp_args]
    ssh_argv.append(" ".join(shlex.quote(a) for a in remote_cmd))
    return ssh_argv


def run_wp_cli(cfg: dict, wp_args: list, *, parse_json: bool = True,
               timeout: int = DEFAULT_TIMEOUT):
    """
    Ejecuta `wp <args>` en el host remoto vía SSH.
    Si parse_json=True, agrega `--format=json` y devuelve el JSON parseado.
    Sino devuelve stdout crudo (str).
    """
    ssh_cfg = cfg.get("ssh") or {}
    args    = list(wp_args)
    # extra_args en config se aplica a todas las llamadas (ej. --skip-plugins=...)
    extra = cfg.get("wp_extra_args") or []
    if extra:
        args.extend(extra)
    if parse_json and not any(a.startswith("--format=") for a in args):
        args.append("--format=json")

    argv = _build_ssh_cmd(ssh_cfg, args)
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise WPRemoteError(f"timeout ({timeout}s) ejecutando: {' '.join(wp_args)}") from e
    except FileNotFoundError as e:
        raise WPRemoteError("ssh no encontrado en PATH") from e

    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()[:300]
        raise WPRemoteError(
            f"wp {' '.join(wp_args)} falló (exit={proc.returncode}): {stderr or '(sin stderr)'}"
        )

    out = proc.stdout
    if not parse_json:
        return out
    try:
        return json.loads(out) if out.strip() else []
    except json.JSONDecodeError as e:
        raise WPRemoteError(
            f"JSON inválido en respuesta de `wp {' '.join(wp_args)}`: {e}"
        ) from e
