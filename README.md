# mapealo

Mapa de arquitectura interactivo para Claude Code. Dos cosas en un plugin:

- **Mapeá un proyecto.** Python (Flask / FastAPI), Next.js o WordPress. Analiza
  el código y dibuja módulos, funciones, modelos, rutas, imports y
  dependencias.
- **Mapeá tu ecosistema de agentes.** Agentes, skills, slash commands, plugins,
  servidores MCP y hooks de tu máquina, con las aristas entre ellos: qué skill
  viene de qué plugin, qué componente nombra a qué otro.

Todo se autodetecta. No hay rutas que configurar.

## Instalación

```
/plugin marketplace add <url-de-este-repo>
/plugin install mapealo@mapealo
```

Reiniciá la sesión. Para el visualizador hacen falta dos paquetes:

```bash
python3 -m pip install fastapi uvicorn
```

Generar el mapa no necesita nada más que Python 3.10+.

## Uso

```
/mapealo                  lista lo que encontró y te deja elegir
/mapealo mi-proyecto      por nombre
/mapealo ~/dev/mi-app     por ruta
/mapealo .                el proyecto en el que estás
/mapealo agentes          tu ecosistema de agentes
/mapa                     abre el visualizador de lo ya mapeado
```

También responde en lenguaje natural: "mapeá este proyecto", "mostrame mis
skills y plugins", "qué MCP tengo conectados", "abrí el mapa".

## Qué detecta, y dónde lo busca

**Proyectos**, por orden de precedencia:

1. `JARVIS_MAP_APPS_DIR` (lista separada por `:`)
2. `~/.config/jarvis-map/config.json` → `{"apps_dirs": ["/ruta/a/mis/repos"]}`
3. autodetección: `~/proyectos`, `~/projects`, `~/dev`, `~/src`, `~/code`,
   `~/repos`, `~/work`, `~/workspace` y variantes
4. una ruta explícita, que siempre gana

Para ver qué resolvió:

```bash
python3 ~/.claude/plugins/cache/*/mapealo/*/engine/mapealo.py --roots
```

**Ecosistema de agentes**, por las convenciones de Claude Code:

| Fuente | Qué sale |
|---|---|
| `~/.claude/agents/*.md` | subagentes |
| `~/.claude/skills/**/SKILL.md` | skills, incluidas las sincronizadas |
| `~/.claude/commands/**/*.md` | slash commands |
| `~/.claude/plugins/` | plugins instalados y las skills que traen |
| `~/.claude.json`, `<proyecto>/.mcp.json` | servidores MCP |
| `~/.claude/settings.json` | eventos con hooks |
| `<directorio>/CLAUDE.md` | cada directorio con instrucciones propias |
| `<proyecto>/.claude/` | lo mismo con scope de proyecto |

Lo mismo aplica si usás `CLAUDE_CONFIG_DIR` para mover el directorio de
configuración.

## Dónde escribe

- `<proyecto>/.jarvis-map/` - los datos del grafo. Si el proyecto está en git,
  conviene agregarlo al `.gitignore`.
- `~/.local/share/jarvis-map/apps/agentes/` - el mapa del ecosistema, que no
  pertenece a ningún proyecto.

Nada más. El análisis es local: lee tus archivos y los deja en tu disco, no
manda nada a ningún servicio. El visualizador escucha solo en `127.0.0.1`.

## Requisitos

- Python 3.10 o más nuevo
- `fastapi` y `uvicorn`, solo para el visualizador
- Linux o macOS (en Windows anda bajo WSL)
