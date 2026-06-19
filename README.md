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

Vista manual por fecha, sin enviar nada:

```powershell
python -m mundialera.interfaces.cli run next --limit 8 --json
```

Filtra por la fecha objetivo en el JSON de salida. El comando ejecuta scraping,
research web, Codex, construccion de prompt, matriz de marcadores y optimizador
de puntos esperados, pero no escribe en GolPredictor.

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
enviadas contra resultados ya publicados, actualiza la base
`.pmundialera/pmundialera.sqlite3` y regenera la memoria de aprendizaje dentro de
esa misma base. Esa memoria entra en el siguiente prompt de Codex.

La automatizacion de Windows no consulta cada minuto cuando no hay ventana activa:
primero lee los horarios de GolPredictor, calcula el proximo despertar antes de la
ventana de 35 minutos y duerme hasta ese momento. Dentro de una ventana activa usa
el intervalo corto configurado.

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

El sistema construye un prompt Markdown con secciones de rol, evidencia,
memoria de torneo/aprendizaje, reglas de decision, gaps de evidencia, contrato
de salida y contexto JSON. El formato del prompt mejora la legibilidad para el
LLM, pero la respuesta exigida sigue siendo JSON puro.

El prompt incluye:

- partido, grupo, kickoff y pronostico actual
- evidencia web deduplicada y hechos estructurados con ids
- historico visible en GolPredictor
- cobertura faltante compacta, sin errores tecnicos como evidencia futbolistica
- dimensiones obligatorias: equipos, torneo, jugadores, jugadores diferenciales,
  jugadores estrella/desequilibrantes, arbitros, faltas/tarjetas, hinchada,
  sede/cancha/clima, titularidad, suplencia, lesionados/sancionados/convocados,
  ritmo, ataque y defensa
- `scoreline_distribution`, perfil probabilistico derivado de esa matriz,
  candidatos por puntos esperados GolPredictor y marcador optimizado
- calibracion de evidencia, empate y sesgo de favorito
- memoria de torneo recortada al partido, el grupo cuando este mapeado y un prior
  global compacto; no se inyecta estado detallado de selecciones ajenas
- reglas de salida JSON

La seleccion final del marcador no depende solo del texto del LLM. Cuando existe
perfil probabilistico, el sistema calcula una matriz de marcadores y maximiza:

```text
EP(h,a) = 5 * P(misma clase 1X2)
        + 2 * P(goles local = h)
        + 2 * P(goles visitante = a)
        + 1 * P(diferencia = h-a)
```

En eliminatorias los pesos se duplican. El `primary` guardado es el marcador con
mayor punto esperado, no necesariamente el marcador exacto modal; `hedge` cubre
una incertidumbre real con EP competitivo.

Codex debe devolver JSON valido, sin Markdown ni texto adicional:

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
ranking, clima, sede, arbitro, xG/tiros, atajadas, corners, balon parado, under/over,
ambos anotan o contexto reciente, el prompt exige reflejarlo como gap de evidencia.
Ademas calcula una calibracion explicita de riesgo de empate, sesgo por favorito,
calidad de evidencia y categorias faltantes antes de seleccionar marcador.

Antes de guardar o enviar, el orquestador aplica guardrails de decision:

- limita la confianza cuando la evidencia es baja o faltan categorias criticas
- reduce marcadores comodos de favorito si no hay soporte de portero, estadistica reciente,
  balon parado y conversion
- cubre empate en el hedge solo cuando compite con el favorito y no por
  incertidumbre generica
- persiste perfil probabilistico, matriz de marcadores, candidatos EP y flags de
  decision en el historico local

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

La persistencia local en `.pmundialera/pmundialera.sqlite3` guarda tanto las
predicciones como el briefing de investigacion por partido. La tabla
`match_research` conserva equipos, torneo/grupo, evidencia textual, evidencia
estructurada por categoria, incertidumbres, calibracion, perfil probabilistico y
`scoreline_distribution`, `expected_points_candidates` y un indice de
dimensiones para jugadores, titulares, suplentes, lesionados, convocados,
arbitraje, faltas/tarjetas, hinchada, sede/cancha/clima, ritmo, ataque, defensa
y jugadores diferenciales. Tambien persiste `star_player_signals` como dato
dedicado para estrellas o jugadores desequilibrantes que puedan subir techo
ofensivo, BTTS, over o cambiar el riesgo de marcador. Para auditoria del prompt
tambien guarda campos dedicados: `team_state_signals`, `lineup_signals`,
`bench_rotation_signals`, `availability_signals`, `player_discipline_signals` y
`rhythm_signals`.

Los agentes deben tratar `memory/` como la fuente canonica. La memoria de torneo
puede conservar agregados globales, pero el prompt final solo debe inyectar
estado de los dos equipos, contexto del mismo grupo cuando este mapeado y un
prior global compacto. Paginas genericas de xG/corners, errores de busqueda y
tareas de investigacion no cuentan como evidencia futbolistica.

## Validación

```powershell
ruff check .
mypy src
pytest
```
