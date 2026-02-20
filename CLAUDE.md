# Inkscape MCP Server (inkmcp)

## Descripción

MCP server que controla Inkscape en tiempo real via D-Bus desde Claude Code.
Fork/clone de [Shriinivas/inkmcp](https://github.com/Shriinivas/inkmcp).

## Arquitectura

```
Claude Code ──(stdio)──> MCP Server (FastMCP 3.0.0) ──(JSON /tmp/)──> gdbus ──(D-Bus)──> Inkscape Extension
                         inkscape_mcp_server.py                                            inkscape_mcp.py (ElementCreator)
```

- **Transporte MCP**: stdio (configurado en `~/.claude/mcp.json`)
- **IPC con Inkscape**: archivos JSON temporales en `/tmp/`
  - Request: `/tmp/mcp_params.json`
  - Response: `/tmp/mcp_response_*.json`
- **D-Bus**: `gdbus call` activa la acción `org.khema.inkscape.mcp` en Inkscape
- **Requisito**: Inkscape debe estar corriendo ANTES de iniciar Claude Code

## Entorno

- **Inkscape**: 1.4.2 (`/usr/bin/inkscape`)
- **D-Bus**: session bus, `gdbus` en `/usr/bin/gdbus`
- **Extensión instalada en**: `~/.config/inkscape/extensions/` (inkscape_mcp.py + inkscape_mcp.inx + inkmcp/)
- **Venv**: `~/.config/inkscape/extensions/inkmcp/venv/` (fastmcp 3.0.0, inkex 1.4.1, lxml 5.4.0, PyGObject 3.54.5)
- **Dependencia de sistema**: `libgirepository-2.0-dev` (para compilar PyGObject)
- **OS**: Ubuntu Linux, Python 3.12

## Instalación realizada

1. Repo clonado a `~/proyectos/inkmcp/`
2. Extensión copiada a `~/.config/inkscape/extensions/`:
   - `inkscape_mcp.py` (entry point)
   - `inkscape_mcp.inx` (metadata XML)
   - `inkmcp/` (paquete completo)
3. Venv creado en `~/.config/inkscape/extensions/inkmcp/venv/`
4. Dependencia de sistema instalada: `sudo apt install libgirepository-2.0-dev`
5. MCP config en `~/.claude/mcp.json` (entrada `"inkscape"`)
6. Skill `/inkscape` creado en `~/.claude/plugins/inkscape-engineer/`
7. Comando `/inkscape` creado en `~/.claude/commands/inkscape.md`

## Herramienta MCP

**Una sola herramienta universal**: `mcp__inkscape__inkscape_operation(command: str)`

Verificada funcionando como herramienta nativa de Claude Code (aparece en la lista de tools).

### Crear elementos SVG
```
rect id=my_rect x=100 y=50 width=200 height=100 fill=blue stroke=black stroke-width=2
circle id=my_circle cx=150 cy=150 r=75 fill=#ff0000
text id=my_text x=50 y=100 text='Hello World' font-size=16 fill=black
path id=my_path d='M 20,50 C 20,50 80,20 80,80'
line, ellipse, polygon, polyline
```

### Grupos con hijos
```
g id=scene children=[{rect id=bg x=0 y=0 width=200 height=200 fill=white}, {circle id=sun cx=100 cy=50 r=20 fill=yellow}]
```

### Gradientes (van a <defs> automáticamente)
```
linearGradient id=grad1 x1=50 y1=50 x2=150 y2=50 gradientUnits=userSpaceOnUse children=[{stop offset=0% stop-color=red}, {stop offset=100% stop-color=blue}]
rect id=shape x=50 y=50 width=100 height=100 fill=url(#grad1)
```

### Filtros y patrones (van a <defs> automáticamente)
```
filter id=blur children=[{feGaussianBlur stdDeviation=5}]
pattern id=dots width=20 height=20 patternUnits=userSpaceOnUse children=[{circle cx=10 cy=10 r=3 fill=gray}]
```

### Ejecutar código Python (inkex) — EL MÁS PODEROSO
```
execute-code code='rect = inkex.Rectangle(); rect.set("x", "100"); rect.set("y", "100"); rect.set("width", "50"); rect.set("height", "50"); rect.set("fill", "green"); svg.append(rect)'
```

Variables disponibles en execute-code:
- `svg` — documento SVG raíz (NO usar `self.svg`)
- `self` — instancia de la extensión
- `inkex.*` — todas las clases inkex (Circle, Rectangle, Path, etc.)
- `get_element_by_id(id)` — buscar elemento por ID
- `math`, `random`, `json`, `re`, `os`, `lxml.etree`

### Consultas
```
get-info                          → dimensiones, viewBox, conteo de elementos (FIXED: ahora muestra todos los detalles)
get-selection                     → elementos seleccionados
get-info-by-id id=element_id      → info de un elemento específico (label, atributos, estilos)
export-document-image format=png return_base64=true  → screenshot del viewport
export-document-image format=pdf output_path=/tmp/output.pdf  → export directo a PDF
export-document-image format=pdf output_path=/tmp/out.pdf area=drawing  → export solo área de dibujo
```
Formatos de export soportados: `png`, `pdf`, `eps`, `ps`

### Abrir archivos
```
open-file path=/path/to/file.svg       → abrir SVG en Inkscape
open-file path=/path/to/figure.pdf     → abrir PDF para editar
```
Usa D-Bus directamente (`org.gtk.Application.Open`), no pasa por la extensión.

### Templates de publicación
```
list-templates                         → listar templates disponibles (built-in + custom)
get-template name=nature               → info detallada del template
apply-template name=nature             → aplicar estilo Nature al documento actual
apply-template name=science            → estilo Science/AAAS
apply-template name=elsevier           → estilo Elsevier (serif, traditional)
apply-template name=ieee               → estilo IEEE (grayscale-safe)
apply-template name=colorblind_safe    → paleta Wong 2011 colorblind-safe
```
Opciones: `apply_fonts=true/false`, `apply_colors=true/false`, `color_map='{"#old":"#new"}'`

### Custom templates
```
save-template name=my_style palette=#e6550d,#2171b5,#31a354 description='My custom style'
save-template name=my_style fonts={...} colors={...} axes={...}     → full JSON config
save-template name=nature force=true palette=#ff0000,#0000ff        → override built-in (requires force)
delete-template name=my_style                                       → eliminar custom (no permite borrar built-in)
```
Custom templates se guardan en `~/.config/inkscape/extensions/inkmcp/user_templates.json` (separado de built-in).
`capture_template_from_svg()` permite capturar fonts/colores/ejes de un SVG existente via código.

### Batch processing (no requiere Inkscape GUI)
```
batch-improve path=/dir/ template=nature format=pdf                → procesar todos los SVG/PDF del directorio
batch-improve path=/dir/ template=science output=/dir/improved/    → directorio de salida custom
batch-improve path=fig1.pdf,fig2.pdf template=colorblind_safe      → archivos específicos separados por coma
batch-improve path=/dir/ template=nature auto_color=true           → auto-detectar y mapear colores a la paleta
batch-improve path=/dir/ template=nature incremental=true          → solo procesar archivos que cambiaron
batch-improve path=/dir/ template=nature report=true format=svg    → generar HTML report before/after
```
Opciones: `format=pdf/svg/png`, `cleanup_matplotlib=true/false` (auto por defecto), `auto_color`, `incremental`, `report`

**Deep matplotlib cleanup** (automático cuando se usa un template):
- **Spine removal**: elimina bordes top/right, mantiene bottom/left (Tufte style), aplica color/width del template
- **Grid restyling**: re-estiliza grid lines (color, width, dashed/dotted) según el template
- **Data recoloring**: mapea colores de datos (barras, líneas, patches) a la paleta del template via deltaE CIE76

### Batch analysis (dry-run)
```
batch-analyze path=/dir/                    → análisis sin modificar: elementos, colores, matplotlib
batch-analyze path=/dir/ template=nature    → análisis + sugerencia de color mapping a la paleta
```
Retorna: conteo de elementos por tipo, colores de datos (no grises), detección matplotlib, mapping sugerido.

### Batch watch
```
batch-watch path=/dir/ template=nature format=pdf             → watch con defaults (5s intervalo, 300s duración)
batch-watch path=/dir/ template=nature interval=10 duration=600  → timing custom
```
Monitorea el directorio y re-procesa archivos que cambien. Usa manifest `.batch_manifest.json` para tracking incremental.

## Gestión de IDs

- **SIEMPRE** especificar `id=` en cada elemento para poder modificarlo después
- Colisiones: si `"house"` ya existe, se crea `"house_1"` automáticamente
- La respuesta incluye `id_mapping` con los IDs solicitados → reales

## Colocación automática

- Elementos visuales (rect, circle, text, path, g...) → capa activa o `<svg>` raíz
- Definiciones (linearGradient, radialGradient, filter, pattern) → `<defs>` automáticamente
- **NO** crear gradientes como hijos de grupos — crearlos como comandos separados

## Workflow probado: Mejora de figuras de paper

Se probó exitosamente con `fig_model_comparison.pdf` del proyecto earthdata-mcp-server.

### Proceso completo
1. Abrir PDF en Inkscape (`inkscape archivo.pdf`)
2. Inspeccionar estructura: `get-info` → ver conteo de elementos
3. Listar textos via execute-code (iterar `svg.iter()`, filtrar `tag == "text"`)
4. Listar paths via execute-code (identificar barras por `fill:`, grid por `stroke:`)
5. Aplicar mejoras (ver abajo)
6. Guardar SVG via execute-code + convertir a PDF via `inkscape` CLI

### Mejoras aplicadas (checklist de publicación)

| Mejora | Detalle |
|--------|---------|
| **Paleta colorblind-safe** | `#2171b5` (azul) + `#e6550d` (naranja), opacity 0.9 |
| **Fondos transparentes** | `fill:none;stroke:none` en paths de background |
| **Grid sutil** | Horizontales: `#e0e0e0` width 0.4. Verticales: dashed `#e0e0e0` width 0.5 |
| **Ejes limpios (Tufte)** | Solo bottom + left, `stroke:#333333` width 1.0. Top + right eliminados |
| **Tipografía profesional** | Arial/Helvetica. Título 16px bold #1a1a1a. Labels 12px #333. Ticks 9px #555 |
| **Mejor modelo destacado** | Barras con `stroke:#333333;stroke-width:1.2;opacity:1.0` |
| **Valores bold** | Labels del mejor resultado en `font-weight:bold` |

### Código de ejemplo — Cambiar colores de barras
```python
# Dentro de execute-code:
import re
for elem in svg.iter():
    tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
    if tag == "path":
        style = elem.get("style", "")
        if "fill:#4682b4" in style:  # color original
            style = style.replace("fill:#4682b4", "fill:#2171b5")
            elem.set("style", style)
```

### Código de ejemplo — Cambiar fuentes globalmente
```python
import re
for elem in svg.iter():
    tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
    if tag in ("text", "tspan"):
        style = elem.get("style", "")
        style = re.sub(r"font-family:[^;]+", "font-family:Arial,Helvetica,sans-serif", style)
        elem.set("style", style)
```

### Código de ejemplo — Guardar SVG a archivo
```python
from lxml import etree
svg_str = etree.tostring(svg, pretty_print=True, xml_declaration=True, encoding="UTF-8").decode("utf-8")
with open("/tmp/output.svg", "w") as f:
    f.write(svg_str)
print("Saved: " + str(len(svg_str)) + " bytes")
```

### Conversión SVG → PDF (bash, después de guardar SVG)
```bash
inkscape /tmp/output.svg --export-filename=/tmp/output.pdf --export-type=pdf
```

## Helper Script

`~/proyectos/inkmcp/inkscape_exec.py` — ejecuta código en Inkscape via D-Bus directamente (bypass del MCP server). Útil para debug o cuando el MCP server no está disponible:

```bash
cd ~/.config/inkscape/extensions/inkmcp && source venv/bin/activate
python3 ~/proyectos/inkmcp/inkscape_exec.py 'print("hello from inkscape")'
```

## Skill y Comando

- **Skill**: `~/.claude/plugins/inkscape-engineer/skills/inkscape-ops/SKILL.md`
- **Comando**: `~/.claude/commands/inkscape.md` → `/inkscape <status|improve|annotate|palette|export>`
- **Referencia paletas**: `~/.claude/plugins/inkscape-engineer/skills/inkscape-ops/references/color-palettes.md`

## Gotchas

1. **Inkscape debe estar corriendo ANTES de iniciar Claude Code** — si no, el MCP server no se registra como herramienta nativa. No basta con abrir Inkscape después; hay que reiniciar Claude Code.
2. **Gradientes con objectBoundingBox** pueden no renderizar — usar `gradientUnits=userSpaceOnUse`
3. **Timeout**: 30 segundos por operación
4. **Linux only** — requiere D-Bus (no funciona en Windows/macOS)
5. **`execute-code` usa `svg`**, no `self.svg`
6. **inkex .set() requiere strings** — `rect.set("width", "100")` no `rect.set("width", 100)`
7. **Escapar comillas en execute-code** es delicado — para código complejo, usar el helper script `inkscape_exec.py`
8. **La extensión se auto-registra** al abrir Inkscape — no hay que hacer nada manual (a diferencia de reapy en REAPER)
9. **Los archivos de extensión viven en dos lugares**: el repo en `~/proyectos/inkmcp/` y la copia instalada en `~/.config/inkscape/extensions/`. Si se modifica código, sincronizar con: `rsync -av --exclude='venv/' --exclude='__pycache__/' ~/proyectos/inkmcp/inkmcp/ ~/.config/inkscape/extensions/inkmcp/`
10. **Tests requieren el venv**: `~/.config/inkscape/extensions/inkmcp/venv/bin/python3 -m pytest tests/ -v` (el Python del sistema no tiene `mcp` ni `inkex`)

## Estructura del código

```
~/proyectos/inkmcp/                              # Repo local (fuente)
├── CLAUDE.md                                    # Este archivo
├── inkscape_exec.py                             # Helper script (bypass MCP)
├── inkscape_mcp.py                              # Entry point extensión (ElementCreator)
├── inkscape_mcp.inx                             # Metadata XML para Inkscape
├── inkmcp/
│   ├── main.py                                  # Entry point del MCP server
│   ├── inkscape_mcp_server.py                   # FastMCP server + D-Bus bridge + format_response
│   ├── inkmcpcli.py                             # Parser de comandos + hybrid execution (1002 líneas)
│   ├── run_inkscape_mcp.sh                      # Wrapper: venv + D-Bus env + start
│   ├── requirements.txt                         # fastmcp>=2.0.0, inkex, lxml
│   ├── inkmcpops/
│   │   ├── common.py                            # create_success/error_response, get_element_info_data()
│   │   ├── element_mapping.py                   # get_element_class(), should_place_in_defs(), get_unique_id()
│   │   ├── execute_operations.py                # execute_code() — Python execution in extension context
│   │   ├── export_operations.py                 # export_document_image() — PNG/PDF/EPS/PS export
│   │   ├── template_operations.py               # Template system — list/get/apply publication styles
│   │   ├── batch_operations.py                  # Batch processing — improve/analyze/watch + incremental
│   │   ├── batch_report.py                      # HTML report generator (self-contained, base64 SVG)
│   │   ├── color_utils.py                       # hex↔RGB↔LAB, deltaE CIE76, extract_colors, auto_map
│   │   └── matplotlib_utils.py                  # Matplotlib SVG detection + cleanup
│   └── templates/
│       └── styles.json                          # 5 templates: nature, science, elsevier, ieee, colorblind_safe
├── blender_addon_inkscape_hybrid.py             # Addon Blender (no usado)
├── blender_inkscape_hybrid.py                   # Hybrid Blender-Inkscape (no usado)
├── examples/                                    # Ejemplos blender↔inkscape (no usados)
├── test_hybrid.py                               # Tests hybrid execution
├── testinkmcp.py                                # Tests generales
└── tests/
    ├── test_batch.py                            # 89 tests — batch, dry-run, incremental, watch, report
    ├── test_color_utils.py                      # 30 tests — color conversion, extraction, auto-mapping
    ├── test_parser.py                           # 31 tests — parser de comandos
    ├── test_format_response.py                  # 20 tests — formateo de respuestas
    └── test_templates.py                        # 21 tests — template system

~/.config/inkscape/extensions/                   # Extensión INSTALADA (copia)
├── inkscape_mcp.py
├── inkscape_mcp.inx
└── inkmcp/
    ├── (mismos archivos que arriba)
    └── venv/                                    # Python venv con dependencias
```

## MCP Config (`~/.claude/mcp.json`)

```json
{
  "mcpServers": {
    "reaper": {
      "type": "stdio",
      "command": "/home/franciscoparrao/proyectos/reaper-mcp-server/venv/bin/python3",
      "args": ["-m", "reaper_reapy_mcp"],
      "cwd": "/home/franciscoparrao/proyectos/reaper-mcp-server"
    },
    "inkscape": {
      "type": "stdio",
      "command": "/home/franciscoparrao/.config/inkscape/extensions/inkmcp/run_inkscape_mcp.sh"
    }
  }
}
```

## Otros MCP servers coexistentes

- **REAPER** (`mcp__reaper__*`): 42 tools para producción musical. Requiere REAPER + reapy.
- **Gateway GIS** (`mcp__gateway__*`): 2,728 herramientas GIS (OTB, QGIS, GRASS, SAGA, GDAL, etc.)
- Los tres servers pueden correr simultáneamente sin conflicto.

## Pendientes / Ideas de desarrollo

### Completados
- [x] Fix `get-info` truncado — `format_response()` ahora maneja todos los campos
- [x] Export PDF directo — `export-document-image format=pdf output_path=/tmp/out.pdf` (también eps, ps)
- [x] Tool `open-file` — abre SVG/PDF en Inkscape via D-Bus (`org.gtk.Application.Open`)
- [x] Template system — 5 estilos de publicación: nature, science, elsevier, ieee, colorblind_safe
- [x] Tests automatizados — 241 tests (parser, format_response, templates, batch, color_utils, deep cleanup)
- [x] Batch processing — `batch-improve` procesa múltiples SVG/PDF con templates sin D-Bus
- [x] Matplotlib SVG — detección automática + cleanup (fondo, styles, fonts DejaVu)
- [x] Dry-run / Analysis — `batch-analyze` analiza sin modificar (elementos, colores, matplotlib)
- [x] Auto color mapping — extrae colores dominantes, mapea a paleta via deltaE CIE76 LAB
- [x] HTML Report — `batch_report.html` self-contained con before/after SVG
- [x] Watch mode — `batch-watch` con polling incremental + manifest
- [x] Templates custom — save/delete/capture templates de usuario en `user_templates.json`
- [x] Deep matplotlib cleanup — spine removal (Tufte), grid restyling, data recoloring automático

- [x] Auto-open report — `xdg-open` al generar HTML report (desactivable con `open_report=false`)
- [x] Integración skill `/inkscape` — subcomandos `batch`, `template`, `palette` usan templates + batch automáticamente
