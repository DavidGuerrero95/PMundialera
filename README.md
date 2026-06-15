# PMundialera

Agente Python para investigar partidos, generar pronósticos y operar grupos de
GolPredictor con una arquitectura hexagonal y herramientas MCP.

## Estado

Primera base funcional:

- Cliente GolPredictor con login ASP.NET WebForms, scraping de tablas y envío
  controlado.
- Subagentes especializados para forma deportiva, plantillas, contexto,
  condiciones del partido y calibración de marcador.
- Orquestador que produce dos pronósticos por partido.
- CLI auditable con `dry-run` por defecto.
- Servidor MCP con herramientas para inspección, predicción y envío.
- Reglas canónicas en `memory/` y adaptadores delgados en `.codex/`, `.cursor/`
  y `.agents/`.

## Instalación local

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
python -m pip install -e ".[dev,mcp]"
```

Configura credenciales sin escribirlas en el repositorio:

```powershell
Copy-Item .env.example .env
notepad .env
```

Variables principales:

- `GOLPREDICTOR_USERNAME`
- `GOLPREDICTOR_PASSWORD`
- `GOLPREDICTOR_GROUPS`, por defecto `Mundial CoreX,Mundial FIFA 2026`
- `PMUNDIALERA_SUBMISSION_WINDOW_MINUTES`, por defecto `35`
- `PMUNDIALERA_ENABLE_WEB_RESEARCH`, por defecto `true`
- `PMUNDIALERA_ENABLE_PAGE_SCRAPE`, por defecto `true`
- `PMUNDIALERA_MAX_PAGES_PER_QUERY`, por defecto `2`
- `PMUNDIALERA_PREDICTION_ENGINE`, por defecto `codex`
- `PMUNDIALERA_CODEX_EXECUTABLE`, por defecto `codex`
- `PMUNDIALERA_CODEX_ARGS`, por defecto `exec -`
- `PMUNDIALERA_CODEX_MODEL`, opcional si quieres forzar un modelo disponible
  en tu Codex CLI

## CLI

Validar login:

```powershell
pmundialera golpredictor login-check
```

Listar grupos visibles:

```powershell
pmundialera golpredictor groups
```

Raspar partidos por grupo:

```powershell
pmundialera golpredictor fixtures "Mundial CoreX"
```

Inspeccionar si la grilla tiene campos editables:

```powershell
pmundialera golpredictor inspect "Mundial CoreX"
```

Predecir partidos de la ventana configurada, sin enviar:

```powershell
pmundialera run window --group "Mundial CoreX" --dry-run
```

Ver predicciones de los proximos partidos de ambos grupos, aunque todavia no
esten en ventana de envio:

```powershell
pmundialera run next --limit 2 --json
```

Ejecutar una pasada autonoma sobre todos los grupos configurados:

```powershell
pmundialera run once --dry-run
```

Dejarlo vigilando en modo automatico:

```powershell
pmundialera run watch --interval-seconds 60 --dry-run
```

Registrar automatizacion de Windows al iniciar sesion:

```powershell
.\scripts\windows\register-autostart-task.ps1 -Mode submit -IntervalSeconds 60
```

Registrar y arrancar de una vez:

```powershell
.\scripts\windows\register-autostart-task.ps1 -Mode submit -IntervalSeconds 60 -StartNow
```

Si Task Scheduler devuelve `Acceso denegado`, instala el arranque automatico
por la carpeta Startup del usuario:

```powershell
.\scripts\windows\install-startup-shortcut.ps1 -Mode submit -IntervalSeconds 60 -StartNow
```

Probar el runner sin enviar:

```powershell
.\scripts\windows\run-autonomous.ps1 -Mode dry-run -IntervalSeconds 60 -Iterations 1
```

Quitar la automatizacion:

```powershell
.\scripts\windows\unregister-autostart-task.ps1
.\scripts\windows\uninstall-startup-shortcut.ps1
```

Enviar solo dentro de la ventana de 35 minutos:

```powershell
pmundialera run window --group "Mundial CoreX" --submit
```

La tarea de Windows usa el mismo flujo con `--submit`; si no hay partido dentro
de la ventana, no escribe nada.

El watcher tambien ejecuta retroalimentacion en cada ciclo: compara predicciones
enviadas contra resultados ya publicados, actualiza `.pmundialera/outcomes.jsonl`
y regenera `.pmundialera/learning-memory.md`. Esa memoria entra en el siguiente
prompt de Codex.

Ver estado de aprendizaje:

```powershell
pmundialera feedback status
```

Forzar reconciliacion:

```powershell
pmundialera feedback settle
```

## MCP

Ejecutar servidor MCP por stdio:

```powershell
pmundialera-mcp
```

Herramientas expuestas:

- `golpredictor_login_check`
- `golpredictor_list_groups`
- `golpredictor_scrape_group`
- `predict_match`
- `run_prediction_window`
- `preview_upcoming_predictions`

## Seguridad

No se versionan credenciales. El envío a GolPredictor exige credenciales por
variables de entorno y usa `dry-run` salvo que se pida explícitamente `--submit`.

## Investigación

El flujo real puede activar busqueda web con DuckDuckGo HTML para recolectar
titulares/snippets recientes por partido y, cuando la pagina es HTML accesible,
extraer un resumen limitado de la fuente. Si el proveedor bloquea o no devuelve
resultados, el sistema conserva la incertidumbre explicita en la prediccion en
vez de inventar hechos.

## Motor Codex

La prediccion final se hace por un puerto `PredictionModel`. Por defecto usa
Codex CLI:

```powershell
PMUNDIALERA_PREDICTION_ENGINE=codex
PMUNDIALERA_CODEX_EXECUTABLE=npx
PMUNDIALERA_CODEX_ARGS=-y @openai/codex --search exec -
```

El sistema construye un prompt con:

- partido, grupo, kickoff y pronostico actual
- evidencia web
- historico visible en GolPredictor
- incertidumbres de los subagentes
- reglas de salida JSON

Codex debe devolver:

```json
{
  "primary": {"home": 2, "away": 1},
  "hedge": {"home": 1, "away": 1},
  "confidence": 0.71,
  "rationale": ["razon"],
  "risk_flags": ["riesgo"]
}
```

Si el CLI no puede ejecutarse o devuelve una respuesta invalida, el sistema
mantiene la automatizacion con fallback heuristico y deja la razon en el
rationale. En Windows el alias de la app puede negar ejecucion desde subprocess;
por eso el `.env.example` usa `npx -y @openai/codex --search exec -`.

El research de produccion combina evidencia web deduplicada, scraping HTML limitado y
puntuacion por fuente con los subagentes de analisis. Las fuentes oficiales y medios
reconocidos pesan mas que agregadores o snippets genericos; si faltan alineaciones,
lesionados, jugadores clave, minutos recientes, noticias personales/profesionales, cuotas,
ranking, clima, sede, arbitro o contexto reciente, el prompt exige reflejarlo como gap de
evidencia.

Subagentes actuales:

- forma deportiva
- plantilla
- jugadores individuales y noticias personales/profesionales
- tactica
- contexto sede/clima/cancha
- ranking/ELO
- mercado/cuotas
- arbitraje/disciplina
- descanso/viaje
- tabla e incentivos
- porteros/defensa
- balon parado
- sesgo de mercado/resultados recientes
- busqueda web

## Validación

```powershell
ruff check .
mypy src
pytest
```
