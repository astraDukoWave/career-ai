# Plan: copiloto-tiempo-real

- **plan_id:** C2-PLAN-01
- **Spec:** `docs/specs/copiloto-tiempo-real.md` @ `5b698a0` (C2-SPEC-01,
  aprobado por Jonathan el 29 sep 2026, merge `41d62b1`).
  - Archivo congelado (solo cambia la línea de estado respecto a `5b698a0`),
    sha256 `cc2ccb0cd7d5e07bc7dc1190a0d98f1e9feb2d175479d716c2c6ba737a54b690`.
- **Ramas:** una por grupo de change sets (`ci/minimal`,
  `feat/context-bridge`, `spike/stt-providers`, `feat/realtime-copilot`),
  cada una con su PR a `main`.
- **Lane:** High-risk (API de pago + producción).
- **Estado: APROBADO** por Jonathan el 29 sep 2026, con ajustes de calidad
  al CS-0 delegados a Claude (fixture realista y regla de decisión).

---

## Contexto de dominio (con procedencia)

- **D1 · Deepgram en vivo, v1 (Nova-3).**
  - `language=multi` activa el code-switching inglés/español; para ese modo
    Deepgram recomienda `endpointing=100`.
  - `utterance_end_ms` (mínimo útil 1000) exige `interim_results=true` y
    emite eventos `UtteranceEnd`.
  - SDK instalado: `deepgram-sdk` 7.1.1, `client.listen.v1.connect(...)` con
    `language`, `interim_results`, `utterance_end_ms`, `endpointing`,
    `keyterm`.
  - *Fuente: docs de Deepgram (multilingual code-switching, utterance end),
    sep 2026; introspección del SDK, 29 sep 2026.*
- **D2 · Deepgram Flux Multilingual, v2.**
  - Reconocimiento conversacional con detección de fin de turno por modelo
    (< 400 ms, no por silencio) y code-switching.
  - GA desde el 29 abr 2026, con 10 idiomas que incluyen inglés y español.
  - SDK: `client.listen.v2.connect(model, encoding, sample_rate,
    eot_threshold, eager_eot_threshold, eot_timeout_ms, keyterm,
    language_hint, ...)`; modelo `flux-general-multi`.
  - *Fuente: comunicado de Deepgram, 29 abr 2026; docs de code-switching;
    introspección del SDK, 29 sep 2026.*
- **D3 · Gemini 3.5 Transcribe** (`gemini-3-5-transcribe-live`).
  - STT en streaming, GA, 85+ idiomas con code-switching, vocabulario
    sesgable hasta 1 000 términos.
  - Accesible por la Live API de `google-genai` (`client.aio.live.connect`,
    presente en 2.12.1).
  - Solo candidato de respaldo (CS-0).
  - *Fuente: blog de Google for Developers, sep 2026.*
- **D4 · Captura en Chrome.**
  - El audio de una pestaña se obtiene con `getDisplayMedia` cuando el
    usuario elige la pestaña y marca "Compartir audio de la pestaña"; la
    pista de video se detiene de inmediato.
  - El audio del sistema en macOS requiere macOS 14.2 o superior (fuera del
    objetivo).
  - La máquina objetivo tiene Chrome 150 en macOS 12.
  - *Fuente: addpipe.com y 9to5Google, 2026.*
- **D5 · Heroku** (spec de migración, P1–P7): 30 s para el primer byte;
  ventana rodante de 55 s en conexiones abiertas; pings de WebSocket de
  uvicorn cada 20 s; 512 MB de RAM; un dyno.
- **D6 · Reglas de system design aplicadas** (skill `system-design-spec`,
  destilada de "Backend System Design", Jem Young):
  - Regla 3: WebSocket para audio bidireccional y SSE para la sugerencia
    (contrato existente `meta → chunk* → error? → done`).
  - Regla 6: timeout en toda llamada externa, una reconexión, sin reintentos
    de operaciones no idempotentes.
  - Regla 7: disponibilidad (el modo texto sobrevive a fallas del modo en
    vivo).
  - Regla 9: validar Origin y API key solo en el servidor.
  - Regla 10: CV Engine y copilot comparten la cuota de Gemini; el contrato
    SSE no cambia.
- **D7 · Contratos que se preservan:**
  - La interfaz pública de `llm_client` (4 funciones y excepciones
    tipadas).
  - `router_agent`, que detecta intención e idioma sin LLM.
  - La capa de rutas no tiene lógica; los servicios no importan FastAPI.

## Cumplimiento de proceso

- Cada grupo trabaja en su propia rama, creada antes de tocar archivos.
  Todo entra a `main` vía PR, docs incluidos.
- **Checks requeridos:**
  - Desde CS-1, el workflow de CI en verde.
  - Antes de CS-1: `python -m pytest` y `npm run build` locales, con el
    output en el PR.
- **Desviaciones:** detener, registrarla con disposición `pending-human` y
  pedir decisión. Un "OK" informal no es disposición.
- **Merges:** Claude mergea con merge commit, fijado al SHA revisado, tras
  la aprobación de este plan (delegado por Jonathan el 29 sep 2026).
- **Deploys a producción:** siempre [HUMANO] y con aviso explícito.

## Change sets

### CS-1 · CI mínima

- **Alcance:**
  - `.github/workflows/ci.yml` con dos jobs, en `pull_request` y en `push` a
    `main`, con `permissions: contents: read`:
    - backend: Python 3.11, `pip install -r backend/requirements-dev.txt`,
      `python -m pytest`, más poppler-utils para el test de `pdftotext`.
    - frontend: Node 20, `npm ci`, `npm run build`.
  - `frontend/package-lock.json` generado y versionado, para builds
    reproducibles.
- **Verificación:** run verde en el PR `[ci-run]`; el test de pdftotext
  corre en CI (no skipped).
- **Commits:** `ci: add minimal GitHub Actions workflow` y
  `build(frontend): add package-lock.json`.

### CS-2 · Context Bridge y anti-invención (backend)

- **Archivos:** `schemas/interview.py`, `api/interview.py`,
  `services/llm_client.py`, `backend/tests/`.
- **Qué hacer:**
  - `InterviewTextRequest.context`: objeto opcional con `job_title`,
    `job_posting` (≤ 4 000), `summary`, `skills: list[str]` y `experience:
    list[{title, company, bullets}]`.
  - El tamaño serializado total se limita a 8 KB, truncando primero el texto
    de la vacante y luego los logros más largos (truncado determinista).
  - `generate_suggestion(text, intent, language, context=None)`: parámetro
    opcional, sin romper a los llamadores actuales.
  - Bloque de contexto en el prompt + reglas de REQ-06: solo hechos del
    contexto; ni empresas, ni proyectos, ni cifras inventadas; si no hay
    historia que encaje, estructura con `[tu ejemplo real: …]`.
  - Timeouts (NFR-02): 10 s al primer fragmento y 30 s en total, con
    `asyncio.wait_for` alrededor del `next()` que ya corre en un hilo. Un
    timeout se reporta como `LLMResponseError`, y el SSE lo emite como
    `llm_response`.
  - `wait_for` no puede matar el hilo. Para que un stream colgado no
    ocupe hilos del pool para siempre, el cliente de Gemini lleva además
    `HttpOptions(timeout=30_000)` (en ms, verificado en `google-genai`
    2.12.1).
- **Verificación (pytest):**
  - El prompt con contexto contiene los hechos y las reglas.
  - Sin contexto, el prompt contiene la regla anti-invención.
  - El truncado es estable.
  - Un generador lento dispara el timeout.
  - `/api/interview/text` acepta y reenvía `context`.
- **Commit:** `feat(copilot): ground suggestions in CV and job context`.

### CS-3 · Context Bridge (frontend)

- **Archivos:** `pages/CVGenerator.tsx`, `pages/InterviewCopilot.tsx`,
  `api/client.ts`.
- **Qué hacer:**
  - Al recibir `CVResponse`, guardar el contexto en `localStorage` bajo
    `careerai.context.v1`, con un envoltorio try/catch.
  - `InterviewCopilot` lo lee al montar, muestra "Contexto: <título> — de tu
    último CV" y lo envía en cada sugerencia de texto.
  - Si no hay contexto, mostrar el aviso de REQ-07.
- **Verificación:**
  - `npm run build` en verde.
  - Comprobación en el preview local con Playwright: generar un CV con un
    backend falso, abrir el copiloto y ver el contexto en la petición.
- **Commit:** `feat(ui): pass the last CV as interview context`.
- **Entregable intermedio:** tras CS-2 y CS-3, el modo texto ya responde con
  tus proyectos. Deploy [HUMANO] D-1.

### CS-0 · Spike: elección del proveedor de STT (en paralelo a CS-2/3)

- **Por qué:** el spec aprobó Nova-3 + heurística de turnos (REQ-02/REQ-04).
  Desde abril existe Flux Multilingual, que detecta el fin de turno con un
  modelo en vez de silencios. Es justo el punto más riesgoso de la v1, así
  que se decide con datos antes de CS-4.
- **Alcance:**
  - `backend/scripts/stt_benchmark.py` (fuera de `app/`) y
    `.github/workflows/stt-benchmark.yml`, que usa las secrets del repo.
  - **Disparo:** con un push a la rama `spike/stt-providers`.
    `workflow_dispatch` solo funciona cuando el archivo ya está en `main`, y
    desde este contenedor no se llega a Deepgram (allowlist de red).
  - **Salida:** el propio workflow publica la tabla de resultados como
    comentario en el PR del spike (`GITHUB_TOKEN` con
    `pull-requests: write`), y esta ventana la lee por la API.
  - **Al cerrar el spike:** el workflow se mergea solo con
    `workflow_dispatch`, como benchmark reutilizable para futuras migraciones
    de modelo.
  - Fixture: el guion de 10 preguntas (5 en inglés, 5 en español),
    sintetizado con TTS dentro del workflow; el reporte dice qué motor se
    usó. No se versiona audio de personas.
  - Realismo del fixture (ajuste delegado, 29 sep):
    - 3 preguntas con pausas a media frase (0.8–1.5 s) y muletillas
      ("um", "este…"), porque ese es el caso que corta mal.
    - 1 pregunta mezcla inglés y español.
    - 8 términos técnicos repartidos en el guion (p. ej., `useEffect`,
      Kubernetes, PostgreSQL), para medir la precisión.
    - El audio pasa por Opus a ~24 kbps y vuelve a PCM (el códec de Meet),
      con ruido de fondo leve (SNR ~25 dB).
    - Entre preguntas, 2–4 s de silencio o de respuesta del candidato.
  - Candidatos, con el mismo audio PCM a 16 kHz:
    - A: Nova-3 `multi` + heurística de REQ-04.
    - B: Flux `flux-general-multi` (fin de turno del modelo).
    - C: Gemini 3.5 Transcribe, solo si A y B fallan en vocabulario técnico.
- **Métricas:**
  - Turnos correctamente cerrados (sobre 10).
  - Cortes prematuros: evento de turno antes de que termine la pregunta,
    medido contra los límites conocidos del guion.
  - Latencia fin-de-habla → evento de turno (p50/p90).
  - Precisión automática de términos técnicos: % de los 8 términos del
    guion transcritos tal cual.
  - Tabla de transcripciones para la revisión humana.
  - Compatibilidad: si cada candidato acepta `keyterm` en modo multilingüe.
  - Costo por minuto, según la lista de precios pública vigente.
- **Regla de decisión** (aprobada con este plan; condiciones 1 y 3 ajustadas
  por delegación de Jonathan el 29 sep):
  - Se elige B si cumple las cuatro condiciones:
    1. Cierra ≥ 9/10 turnos, no menos que A y **sin más cortes prematuros
       que A**.
    2. p50 de latencia ≤ A.
    3. Precisión de términos técnicos ≥ A. La revisión de Jonathan (1 min)
       solo desempata.
    4. Costo ≤ 2 veces el de A.
  - Si no, se queda A.
  - Si B gana, se registra la enmienda C2-SPEC-01 v1.1 (redacción de
    REQ-02 y REQ-04). Queda ratificada por esta regla, sin nueva ronda de
    aprobación.
- **Verificación:** artefacto del workflow + comentario en el PR con la
  tabla y la decisión.
- **Commit:** `test(stt): add provider benchmark (spike)`.
- **Depende de:** [HUMANO] H-1.

### CS-4 · Streaming en el backend

- **Archivos:**
  - `services/stt_stream.py` (nuevo): interfaz de sesión y adaptador del
    proveedor ganador.
  - `services/turn_detector.py` (nuevo).
  - `api/interview_audio.py`: reescritura.
  - `config.py` y tests.
- **Qué hacer:**
  - **`stt_stream`** abre la sesión con idioma multi, `keyterm` (≤ 50,
    derivados del contexto) y audio `linear16` a 16 kHz. Normaliza los
    eventos del proveedor a `partial`, `final` y `turn_end`. Timeout de
    conexión de 5 s; `KeepAlive` cuando no llega audio; una reconexión.
  - **`turn_detector`** (puro) clasifica el turno como pregunta (REQ-04).
    La regla de unión solo aplica si gana el candidato A.
  - **Ruta `/api/interview/ws/live`:**
    - Valida `Origin` contra `CORS_ORIGINS` antes de `accept()` (cierre 1008).
    - Límites: 2 sesiones simultáneas y 90 min, configurables.
    - Protocolo:
      - Primer mensaje JSON `{type:"start", source, context}`; luego frames
        binarios PCM.
      - Salida `{type:"partial"|"final"|"turn", text, is_question, turn_id}`
        y `{type:"error", code}`.
  - Se retiran la ruta `/ws/audio` y `transcribe_audio_chunk`
    (reemplazados).
- **Verificación (pytest, con proveedor falso en proceso):**
  - Rechazo de Origin (AC-06).
  - Límites (AC-07).
  - Mapeo de eventos.
  - Proveedor caído → `error` (AC-08).
  - Parseo de mensajes reales del proveedor, capturados en CS-0 como
    fixtures JSON sin audio.
- **Commits:**
  - `feat(stt): stream transcription through a provider adapter`
  - `feat(copilot): detect interviewer questions`
  - `feat(api): live interview websocket with origin and session limits`

### CS-5 · Captura y modo entrevista (frontend)

- **Archivos:** hook nuevo `useLiveAudio.ts` + AudioWorklet (downsample a
  16 kHz Int16); `pages/InterviewCopilot.tsx` (modo entrevista); se borran
  `useAudioCapture.ts` y `AudioCapture.tsx`.
- **Qué hacer:**
  - Selector de fuente: pestaña (`getDisplayMedia`, que detecta la ausencia
    de pista de audio → EDGE-01) o micrófono.
  - Envío de frames de ~100 ms.
  - Transcripción parcial y final; pregunta destacada.
  - Autosugerencia por SSE con contexto; "Sugerir ahora"; 👍/👎.
  - Estado de conexión con una reconexión.
  - Aviso para apps de escritorio (EDGE-02).
- **Verificación:** `npm run build` + el E2E de CS-8.
- **Commit:** `feat(ui): live interview mode with tab or mic audio`.

### CS-6 · Resumen de sesión (instrumentación de las métricas)

- **Qué hacer:**
  - Por pregunta: marca de tiempo del evento `turn`, del primer `chunk` y si
    fue automática o manual, más el 👍/👎.
  - Al detener: preguntas, útiles, latencia p50/p90 y "Copiar resumen" con
    los campos de la bitácora del experimento.
  - Todo en memoria del navegador.
- **Verificación:** la función que calcula el resumen es pura y se prueba
  con una vista mínima; build verde.
- **Commit:** `feat(ui): session summary for the interview experiment`.

### CS-8 · E2E automatizado con audio falso

- **Qué hacer:**
  - Playwright + Chromium con `--use-fake-device-for-media-stream` y
    `--use-file-for-fake-audio-capture=<fixture.wav>` (fuente micrófono).
  - Backend local con proveedor de STT y LLM falsos, inyectados en el test
    con `app.dependency_overrides` o un parámetro de fábrica: sin flags de
    prueba en el código de producción.
  - Flujo: iniciar → transcripción → pregunta detectada → sugerencia → resumen.
  - Job nuevo en la CI.
- **Verificación:** job E2E verde `[ci-run]` (AC-09).
- **Commit:** `test(e2e): live mode with fake audio in CI`.

### CS-7 · Gate de costo y cierre

- **Qué hacer:**
  - Dictamen `cto-review` sobre el deploy del WebSocket en vivo: rollback,
    blast radius, dueño y observabilidad.
  - HANDOFF §2/§4/§8, `CLAUDE.md` (audio y archivos congelados) y `STATE.md`.
- **Verificación:** dictamen entregado; docs en PR.
- **Commit:** `docs: record cycle 2 decisions and state`.

## Tareas [HUMANO]

- **H-1 · Secrets del repo** (antes de CS-0) — ✅ hecho el 29 sep 2026.
  - Dónde: GitHub → Settings → Secrets and variables → Actions → New
    repository secret.
  - Qué: `DEEPGRAM_API_KEY` y `GEMINI_API_KEY`, con los mismos valores de
    Heroku.
  - Las keys **nunca** van al chat. Los workflows de forks no reciben
    secrets.
  - Evidencia: "secrets listas".
- **D-1 · Deploy intermedio** (tras merge de CS-2/3).
  - Qué: `git checkout main && git pull && git push heroku main:main`.
  - Evidencia: línea `web.1: up` y una sugerencia de texto que mencione un
    proyecto de tu CV.
- **H-2 · Prueba rápida de pestaña** (tras deploy de CS-5, 2 min).
  - Qué: en Chrome, compartir la pestaña de un video con audio y ver
    transcripción.
  - Evidencia: sí/no. Si es no, cambiamos al micrófono antes de seguir
    (supuesto técnico NFR-07).
- **D-2 · Deploy final** (tras el dictamen de CS-7): mismo comando.
- **H-3 · E2E humano** (AC-01..05, AC-11).
  - Qué: reunión de Meet; una segunda persona o un video en otra pestaña
    hace de entrevistador con el guion de 10 preguntas;
    `heroku logs --tail -a career-ai` abierto.
  - Evidencia: el resumen copiado y ~50 líneas del log.

## Orden y dependencias

```
CS-1 ─┬─ CS-2 ─ CS-3 ─ D-1
      └─ H-1 ─ CS-0 ─ CS-4 ─ CS-5 ─ H-2 ─ CS-6 ─ CS-8 ─ CS-7 ─ D-2 ─ H-3 ─ verify
```

- CS-2 y CS-3 no esperan a las secrets.
- CS-4 espera la decisión de CS-0.
- Si H-1 no llega, CS-4 arranca con el candidato A (baseline aprobado) y
  CS-0 queda como deuda registrada.

## Tests requeridos

| Qué | Dónde |
|---|---|
| Unit (prompt/contexto, truncado, timeouts, turnos, keyterms) | pytest local y CI |
| WebSocket con proveedor falso (Origin, límites, errores, mapeo) | pytest local y CI |
| Parseo de mensajes reales del proveedor (fixtures JSON de CS-0) | pytest |
| Benchmark de proveedores | workflow_dispatch con secrets |
| E2E con audio falso | CI (CS-8) |
| E2E real en Meet | [HUMANO] H-3 |
| Build del frontend (tsc) | CI |

## Riesgos → mitigación

- **Chrome 150 en macOS 12 no captura el audio de la pestaña** → H-2 lo
  detecta temprano; plan B: micrófono con altavoz o segundo dispositivo.
- **Detección de fin de turno deficiente** → CS-0 decide con datos; "Sugerir
  ahora" siempre disponible.
- **Latencia sobre la meta** → con Flux, el evento temprano de fin de turno
  (`eager_eot_threshold`) permite arrancar el LLM antes; además, prompt más
  corto y medición por pregunta (CS-6).
- **Costo descontrolado** → Origin, 2 sesiones, 90 min y gate de CS-7.
- **Regresión del modo texto** → CS-2 conserva la interfaz pública; tests
  del SSE existentes + nuevos.
- **Secrets expuestas** → solo en Heroku y en las secrets de GitHub; test
  AC-12 (grep del bundle); nunca en logs.
- **Alcance mayor a un sprint** → los entregables intermedios (D-1 y H-2)
  permiten parar con valor si el tiempo se acaba.

## Prompt de respaldo

No aplica: todo lo ejecuta esta ventana. Si algún paso necesitara la
terminal de Jonathan, va en el Loop humano con comandos exactos.

---

*Generado: 29 sep 2026 · Basado en C2-SPEC-01 @ `5b698a0` · Aprobado el 29 sep
2026.*
