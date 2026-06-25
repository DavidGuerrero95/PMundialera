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
- `PMUNDIALERA_POOL_POSITION`, por defecto `40`
- `PMUNDIALERA_POOL_SIZE`, por defecto `50`
- `PMUNDIALERA_POOL_STRATEGY`, por defecto `aggressive_high`
- `PMUNDIALERA_STRATEGY_HORIZON`, por defecto `tournament`
- `PMUNDIALERA_TOURNAMENT_PHASE`, por defecto `final_phase`
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

La tarea programada es el mecanismo recomendado para produccion: ademas del
inicio de sesion, instala un disparador periodico cada 15 minutos. Como el
runner usa mutex, ese disparador no duplica procesos; solo revive el watcher si
Windows cerro el PowerShell oculto, la sesion cambio de estado o el proceso
termino inesperadamente.

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
el intervalo corto configurado. El runner escribe un heartbeat local en
`.pmundialera/watch-heartbeat.json` y ejecuta una auditoria de cobertura para
detectar partidos recientes que ya entraron en ventana sin envio registrado.
Cuando varios partidos comparten hora, `run schedule` y el heartbeat exponen
`next_matches` con todos los partidos del mismo kickoff o todos los activos en la
ventana. `next_match` se conserva solo como resumen compatible.
Para reducir latencia, `run schedule` toma el calendario del primer grupo
configurado como fuente de fixtures; `run once` sigue enviando el mismo marcador
en todos los grupos configurados.

Auditar cobertura de envios recientes:

```powershell
pmundialera run audit --json
```

La auditoria revisa por defecto las ultimas 36 horas. Si un partido ya entro en
ventana y no tiene envio real en SQLite ni pronostico visible en GolPredictor,
aparece como `missing_submission`. Si GolPredictor muestra pronostico pero no
hay registro local, aparece como `platform_prediction_without_local_record`.

Para evitar reenvios repetidos, un `run once --submit` salta cualquier
partido/grupo que ya tenga un envio real exitoso en
`.pmundialera/pmundialera.sqlite3`, salvo que se borre o corrija manualmente ese
registro.

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
perfil probabilistico, el sistema calcula una matriz de marcadores y usa estos
puntos esperados como base:

```text
EP(h,a) = 5 * P(misma clase 1X2)
        + 2 * P(goles local = h)
        + 2 * P(goles visitante = a)
        + 1 * P(diferencia = h-a)
```

En eliminatorias los pesos se duplican. Como la cuenta esta en posicion `40/50`,
el modo actual es `aggressive_high`: el `primary` parte del mayor EP, pero puede
escoger un marcador de mayor margen, mayor total o mayor diferenciacion cuando
queda cerca del lider por EP, mantiene probabilidad exacta minima y respeta los
umbrales de cambio de clase 1X2. La presion de riesgo se calcula como
`(pool_position - 1) / (pool_size - 1)`, que para `40/50` da `0.7959`.
No cambia de ganador si hay favorito fuerte (`>= 0.72`) y solo permite sorpresas
si la clase alternativa esta cerca, el partido esta abierto y no hay favorito
dominante.

El perfil probabilistico aplica regularizacion para evitar sobreentrenar un
marcador bucket como `2-1`. Los priors globales de torneo, listas de ataques
calientes, defensas fragiles u `open_profile` no suben por si solos el BTTS/over
de un partido; solo pesan cuando la evidencia pertenece a los dos equipos, su
grupo o un dato compacto de torneo. Si un favorito claro enfrenta un rival con
estado defensivo muy debil, el xG rival se reduce antes de optimizar EP para no
forzar ambos equipos anotan por inercia.
Cuando mercado, ranking y calidad de plantel marcan superioridad clara, esos
gaps bajan la confianza pero no borran el margen: el perfil puede abrirse a
`2-0`, `0-2` u otros márgenes de dos goles si el xG del underdog queda bajo.

En modo `aggressive_high`, esos otros margenes incluyen `3-0` y `0-3` cuando el
xG del underdog queda bajo y hay soporte de forma/produccion mas ranking,
mercado o calidad de plantel. En partidos abiertos (`over_2_5 >= 0.58` y
`BTTS >= 0.55`) puede preferir `3-1`, `1-3` o `2-2` sobre buckets repetidos
cuando el EP esta cerca. El feedback de los ultimos 24 partidos unicos asentados
se guarda en SQLite como `metadata.strategy_memory` y ajusta total, margen,
empates falsos y repeticion de buckets.
Esa memoria tambien incluye un overlay de la ultima jornada asentada. Si el
ultimo bloque mostro subestimacion de margen, el selector abre margen solo en la
direccion soportada por el perfil: favorito claro + xG/BTTS bajo del rival
prefiere porteria a cero (`2-0`, `3-0`, `0-2`, `0-3`) en vez de un `2-1`
automatico; favorito moderado con BTTS alto no salta a margen de dos sin soporte
adicional de forma, mercado, plantel o fragilidad defensiva.

Para la fase final, `PMUNDIALERA_TOURNAMENT_PHASE=final_phase` aumenta la
presion efectiva de riesgo porque ya existe mas informacion real de cada equipo
en el Mundial. Ese modo permite evaluar candidatos de mayor total o margen como
`3-2`, `2-3`, `4-1` o `4-0`, pero solo si la matriz de marcadores, forma del
torneo, ranking/mercado, plantel, bajas, ataque/defensa y jugadores diferenciales
lo respaldan. No habilita cambios de ganador contra favoritos fuertes ni
marcadores amplios sin soporte probabilistico.

Codex debe devolver JSON valido, sin Markdown ni texto adicional:

```json
{
  "primary": {"home": 2, "away": 1},
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
