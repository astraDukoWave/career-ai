# HANDOFF.md — CareerAI
> Fuente de verdad para cualquier sesión que tome este proyecto.
> Sobrescribir al cerrar cada fase. NO acumular.

---

## 1. Identidad del proyecto

- **Producto:** CareerAI — CV Engine (CV a la medida, una columna,
  ATS-friendly) + Interview Copilot.
- **Repo:** https://github.com/astraDukoWave/career-ai — **PÚBLICO**
  (decisión cerrada, §4).
- **Producción:** https://career-ai-95daf7c9a813.herokuapp.com (Heroku, app
  `career-ai`, container stack, Basic dyno, región us).
- **Replit:** retirado. Se cayó antes del cutover; `.replit` y `replit.nix`
  eliminados.
- **Health check:** `GET /health → {"status": "ok"}`.
- **Stack:** FastAPI · Gemini `gemini-3.1-flash-lite` vía `google-genai` ·
  Deepgram Nova-3 · React/Vite/TypeScript · WeasyPrint.
- **Fase actual:** Ciclo #2 (copiloto en tiempo real) **en producción**
  con la enmienda v1.2 (`0b10c01`, PR #24, desplegada el 13 oct 2026).
  Ya se usó en una entrevista real por teléfono (modo micrófono, 49 min).
  Sus hallazgos (§2) definen el siguiente ciclo del copiloto.

---

## 2. Estado real

### ✅ Funcionando (verificado en producción, 28 sep – 1 oct 2026)

| Feature | Evidencia |
|---|---|
| CV Engine (keywords → score → PDF) | `POST /api/cv/generate` 200 en ~2 s; PDF 200 (logs de Heroku) |
| Plantilla de CV de una columna, skills por grupos, viñetas limpias | PR #3 + suite pytest |
| Download PDF | Funciona en Heroku: el archivo se descarga al momento, antes del ciclo diario del dyno |
| Print to PDF | `f8c228b` |
| Copilot de texto → SSE (`meta → chunk* → error? → done`) | 942 ms, captura del E2E |
| 429 de Gemini → evento SSE `rate_limit`; stream fuera del event loop | `6e74e4f` + prueba offline 8/8 |
| Context Bridge: el copiloto usa el último CV y no inventa (sin CV, marcadores `[your real example: …]`) | PR #9 + E2E de Jonathan en producción (30 sep, videos) |
| Modo en vivo con la pestaña (H-2): 3 preguntas detectadas sin clic, latencia p50 0.7 s / p90 0.7 s | Video y resumen de Jonathan, 1 oct 16:14 (audio de un live de YouTube, 2 min) |
| Modo micrófono v1.2 en una entrevista real (13 oct, teléfono en altavoz, 49 min): la tarjeta no se movió sola y la barra recogió las preguntas; p50 1.0 s / p90 1.4 s | Video de Jonathan, analizado cuadro por cuadro (452 cuadros) + resumen de sesión |
| `careerai-mcp` desde Claude Code (H-MCP): `generate_cv` → score y PDF | Jonathan en su Mac, 1 oct |

### ✅ Desplegado el 1 oct 2026 (D-2, `ee9fef0`)

| Feature | Evidencia |
|---|---|
| WebSocket en vivo `/api/interview/ws/live`: Nova-3 `multi`, Origin, 2 sesiones / 90 min, una reconexión | PR #17: pytest + uvicorn real + revisión independiente (2 mayores corregidos) |
| Detección de turnos y preguntas con continuación v1.1 (AC-13) | Eventos **reales** de Nova-3 recapturados en el PR #18 |
| Modo entrevista: pestaña o micrófono, una tarjeta, Suggest now, 👍/👎 | PR #19 + revisión independiente (1 mayor corregido) |
| Resumen de sesión y "Copy summary" (REQ-08) | PR #20 + Vitest |
| E2E en la CI con audio falso | PR #21, job `e2e · live mode (fake audio)` |
| Servidor MCP `careerai-mcp` (Claude Code / Desktop) | PR #16, job `mcp · pytest` |
| CI en cada PR: pytest, build y arranque de la imagen de producción | PR #7 |
| CORS por variable de entorno | original |

### ❌ Conocidamente roto (se resuelve en el Ciclo #2)

| Issue | Causa | Decisión |
|---|---|---|
| Audio (grabar → Stop) no transcribe; solo español y micrófono | El flujo pre-grabado de `/ws/audio` | **Resuelto** con el modo en vivo (en producción desde D-2) |

### ⚠️ Deuda técnica vigente

- **El CV Engine bloquea el event loop.** Hace llamadas síncronas a Gemini y
  a WeasyPrint dentro de rutas `async`, así que cada CV congela el servidor
  unos segundos. Con usuarios concurrentes, sprint dedicado.
- **Hallazgos de la primera entrevista real (13 oct, modo micrófono).**
  La v1.2 se comportó como se diseñó, pero fue poco útil:
  - De 3 tarjetas, solo 1 era una pregunta real del entrevistador, y llegó
    ~90 s tarde (se abre con clic). La tarjeta 1 respondió como si el
    candidato fuera el entrevistador; la 2 respondió una pregunta del
    propio candidato, en voz de la empresa.
  - La barra tuvo 39 entradas: 10 preguntas reales, 18 muletillas o
    afirmaciones ("¿vale?", "¿no?", "¿ok?") y 11 frases del candidato.
  - La tarjeta estuvo fuera de la pantalla en el 81 % de los cuadros: la
    página quedó desplazada hacia la transcripción.
  - **Ritmo:** pausa mediana de 0.51 s (p90 1.27 s); el 94 % de las pausas
    duran menos de 1.5 s. Una sugerencia que llega ≥1 s después del cierre,
    más el tiempo de leerla, va detrás de la conversación. El candidato la
    usó solo en los dos silencios más largos (3.7 s y 2.7 s).
  - **Transcripción:** "Cloud" por Claude, "API de Tropic" por Anthropic,
    "Carrier AI" por CareerAI. Hay que verificar si las keyterms llegan a
    Nova-3 con `language=multi` o si cae al reintento sin ellas.
  - **Siguiente ciclo del copiloto** (spec + cto-review; zona congelada):
    separar las voces (diarización o enrolamiento de voz) e ignorar los
    turnos del candidato; no tratar muletillas como preguntas; regla de
    perspectiva en el prompt (siempre como el candidato); pistas de 2–3
    viñetas antes del párrafo, en un panel que no se va de la pantalla; y
    sugerencia especulativa sobre los parciales para ganarle a la pausa
    de 0.5 s.
- **Calibración pendiente del modo pestaña:** `TURN_CONTINUATION_S` (1.5 s)
  y `STT_ENDPOINTING_MS` (100) solo se han medido con YouTube (H-2); falta
  una reunión real en Meet (H-3, opcional ahora).
- **Sin autenticación:** el costo del modo en vivo lo acotan los límites
  (2 sesiones, 90 min); peor caso ~USD 17 al día. Jonathan aceptó el riesgo
  para el piloto con la URL sin difundir. El tope duro es el saldo prepagado
  de Deepgram con Auto-reload apagado (Deepgram no tiene una alerta de uso
  configurable confirmada; avisa por correo cuando el crédito baja). El
  login llega en el Ciclo #3.
- **Demo pública sin límite de peticiones.** La key de Gemini tiene billing
  con tope; hace falta un rate limit antes de difundir la URL.
- **Sin protección de `main`.** La CI corre en cada PR, pero no es
  obligatoria a nivel de GitHub.
- **Postgres y Redis** están en `docker-compose` pero no conectados (Phase
  3).
- **`gemini-3.1-flash-lite`** es GA, con apagado anunciado para el 7 may
  2027. Hay que migrar antes con `GEMINI_MODEL` + `_MODEL_ALIASES`.

---

## 3. Arquitectura (producción en Heroku)

```
Heroku app career-ai (container stack, Basic dyno)
└── Imagen multi-stage (Dockerfile raíz): build del frontend (Node 20) +
    Python 3.11 + libs nativas de WeasyPrint
    └── uvicorn app.main:app … --workers 1 --ws-max-size 1048576 --ws-max-queue 8
        --ws-per-message-deflate false   (heroku.yml → run.web; la CI arranca con él)
        ├── /api/cv/generate · /api/cv/{archivo}/pdf
        ├── /api/interview/text        → SSE (Gemini)
        ├── /api/interview/ws/live     → WS en vivo → Deepgram Nova-3
        ├── /health
        └── /*                         → frontend/dist (StaticFiles)
```

- **Deploy** (lo ejecuta Jonathan tras cada merge a `main`):
  `git push heroku main:main`. El build es remoto; `VITE_API_URL` va en
  `build.config` de `heroku.yml`.
- **Rollback:** `heroku rollback -a career-ai`.
- **Logs:** `heroku logs --tail -a career-ai`.
- **Límites de plataforma** (spec de Heroku, P1–P9):
  - 30 s para el primer byte (H12).
  - Ventana rodante de 55 s en conexiones abiertas.
  - 512 MB de RAM.
  - El ciclo diario del dyno borra `/tmp`.

---

## 4. Decisiones técnicas cerradas (no reabrir sin justificación)

| Decisión | Elegido | Razón |
|---|---|---|
| LLM | `gemini-3.1-flash-lite` vía `google-genai` 2.12.1, con alias para modelos retirados | Los modelos 2.x se cerraron a cuentas nuevas (jul 2026); se eligió por descubrimiento empírico |
| STT | Deepgram Nova-3 en **streaming** (Ciclo #2) | Reabierto por Jonathan el 28 sep 2026: una entrevista es en tiempo real |
| Captura de audio (Ciclo #2) | Pestaña de la reunión en Chrome (principal) + micrófono (respaldo) | No pide permisos de sistema; macOS 12 no permite capturar el audio del sistema |
| PDF | WeasyPrint (Download) + Print to PDF | Download funciona en Heroku |
| Plantilla de CV | Una columna, encabezados estándar, US Letter | Las dos columnas intercalaban el texto al extraerlo (verificado con pdftotext) |
| Intent routing | Por palabras clave (sin LLM) | < 10 ms |
| CORS | Por variable de entorno, NUNCA `["*"]` con credentials | La spec HTTP lo prohíbe |
| Auth | Sin auth hasta Phase 3 | — |
| Deploy de producción | Heroku Basic dyno (container), deploy desde `main` | Crédito estudiantil; monolito sin split |
| Visibilidad del repo | Público | Portfolio verificable |
| Secretos | Heroku Config Vars / `.env` local; placeholders en docs | El repo es público |
| Merges | Claude mergea los PR aprobados con merge commit (nunca squash); Jonathan ejecuta los deploys | Acordado el 29 sep 2026 |
| Reescritura de bullets por LLM | Apagada por defecto (`CV_REWRITE_BULLETS`); el copiloto recibe solo las palabras del candidato | PR #10: en un CV real metió 8 afirmaciones falsas |
| STT en vivo | Nova-3 `multi` + REQ-04 con continuación (C2-SPEC-01 v1.1) | Benchmark en tiempo real, PR #11 (30 sep 2026) |
| Cliente de Deepgram | API WebSocket directa con `websockets` 16.1.1, sin SDK | Lo mismo que midió el CS-0; testeable contra un Deepgram falso local (PR #17) |
| Continuación v1.1 | Ventana encadenada: el habla dentro de 1.5 s, una muletilla sin transcribir incluida, sigue el turno con el mismo `turn_id`; máx. una ráfaga sin palabras | Eventos reales de Nova-3 (PR #18) y revisión independiente |
| Pruebas de turnos | Con eventos reales grabados del proveedor, nunca inventados | La reconstrucción del primer intento no probaba AC-13 |
| Límites de WebSocket | Flags de uvicorn en `heroku.yml`: 1 worker, frames de 1 MiB, cola de 8, sin deflate | La revisión probó 639 MB de memoria con frames comprimidos |

---

## 5. Estrategia comercial — fuera del repo

El mapa competitivo, el posicionamiento y el pricing viven en `strategy.md`,
un documento privado del Proyecto career-ai en Claude. Ningún análisis de
competidores, precio objetivo ni estrategia de go-to-market entra a este
repo; los specs lo referencian sin copiarlo.

---

## 6. Roadmap

1. **Ciclo #2 — Copiloto en tiempo real** (`docs/specs/copiloto-tiempo-real.md`,
   aprobado el 29 sep 2026). En producción desde el 1 oct; falta H-3:
   - Escucha la pestaña de la reunión y transcribe en streaming en
     inglés/español.
   - Detecta preguntas y sugiere sin clics.
   - Context Bridge + regla anti-invención.
   - Modo entrevista y resumen de sesión.
   - Validación de Origin, límites, timeouts y CI.
2. **Ciclo #3 — Perfil verificable (GitHub como fuente de verdad):**
   - **Login con GitHub** (decidido el 1 oct 2026). Un perfil por usuario
     necesita identidad, y GitHub OAuth da en un paso la identidad y el
     permiso para leer sus repos. También cierra el riesgo de costo: el
     modo en vivo queda solo para usuarios con sesión. Pagos y planes
     siguen en Phase 3.
   - Perfil maestro construido desde GitHub (repos, commits, PRs, stack) más
     un cuestionario corto de confirmación. Cada línea del CV lleva su
     evidencia (enlace) o la confirmación del usuario.
   - Botón "Actualizar": vuelve a leer GitHub y propone cambios que el
     usuario acepta o rechaza, como un PR de su perfil.
   - CV a la medida por vacante que selecciona, ordena y traduce hechos con
     evidencia, sin inventar. Las palabras faltantes se muestran como huecos
     que el usuario confirma.
   - También: importar el CV en PDF, sección de Proyectos y el "ATS %"
     renombrado a "coincidencia con la vacante".
   - Dogfood antes de construir: el perfil maestro de Jonathan (29–30 sep)
     se armó a mano desde sus repos.
3. **Practice Mode:** simulador de entrevistas con reclutador IA, derivado de
   la skill `ai-recruiter-interview-coach` y de las métricas de las primeras
   sesiones reales.
4. **Phase 3:** pagos y planes (el login y la base de datos del perfil
   llegan antes, con el Ciclo #3).
5. **Deuda:** event loop del CV Engine, rate limit, protección de `main`.

### Learning Backlog (única lista de oportunidades)

- **LB-01 · Perfil verificable desde GitHub** → Ciclo #3 (arriba).
  [hipótesis] Evita CVs con experiencia inventada y reduce el tiempo de
  armar un CV a la medida.
- **LB-02 · Radar de vacantes.** Recomendaciones periódicas basadas en el
  perfil verificado, cada una con su encaje y sus huecos.
  - Experimento dogfood con Jonathan antes de construir.
  - Métricas: % de recomendaciones a las que aplica y tasa de respuesta
    contra su búsqueda manual.
  - Fuera de alcance: aplicar automáticamente y scraping de sitios cuyos
    términos lo prohíben.
- **LB-03 · Servidor MCP de CareerAI.** ✅ v0 local mergeado (PR #16,
  `mcp/`) y probado por Jonathan desde Claude Code (H-MCP, 1 oct). El
  servidor remoto llega con el login.
- **LB-04 · Practice Mode por voz.** Modelos voz a voz para el reclutador
  simulado; se evalúa al entrar a Practice Mode.
- **LB-05 · Brief previo a la llamada.** Antes de la entrevista: qué hace la
  empresa, preguntas probables y respuestas ancladas al perfil verificable,
  más qué precisar con honestidad. Dogfood del 13 oct: se armó a mano y fue
  lo que más sirvió en una llamada fluida, donde la sugerencia en vivo
  llegaba tarde. [hipótesis] Más útil que el copiloto en filtros de
  reclutador; el copiloto rinde más en preguntas técnicas largas.

---

## 7. Metodología (modo una ventana, desde el 29 sep 2026)

- Claude trabaja como CTO y ejecutor en una sola ventana y carga cada skill
  en su etapa:
  - `brainstorm → design-spec (+ system-design-spec) → design-plan`
  - ejecución: rama, commits, push y PR
  - `verify` → merge tras la aprobación.
- **Skills:**
  - v0.3: `workflow-router`, `design-plan`, `verify`.
  - v0.2: `brainstorm`, `design-spec`, `system-design-spec`, `cto-review`.
- **Jonathan:**
  - Aprueba specs, planes y ratificaciones.
  - Ejecuta los deploys a Heroku.
  - Hace los E2E que piden navegador o micrófono.
  - Maneja los secretos.
- **Evidencia:** CI/tests/smoke contra la URL viva > inspección del diff >
  reportes. Etiquetas: `[verified-this-session]` · `[inherited-unverified]` ·
  `[contradicted]`.
- **Reglas fijas:**
  - Nada vive solo en el working tree.
  - Todo cambio a `main` pasa por PR.
  - Ningún "listo" se acepta sin verificación contra el repo real.

---

## 8. Archivos clave

| Archivo | Propósito |
|---|---|
| `HANDOFF.md` | Fuente de verdad entre fases (v3, 29 sep 2026) |
| `STATE.md` | Ciclo activo y cola |
| `docs/specs/` | `migracion-monolito-heroku.md`, `migracion-sdk-gemini.md`, `copiloto-tiempo-real.md` |
| `docs/plans/` | Un plan por ciclo |
| `backend/app/services/cv_format.py` | Normalización de skills y viñetas |
| `backend/tests/` | Suite pytest (sin red ni API keys) |
| `backend/app/services/llm_client.py` | Gemini (`google-genai`) + prompts |
| `backend/app/services/stt_stream.py` · `turn_detector.py` · `live_session.py` | Modo en vivo: Deepgram, turnos y sesión |
| `frontend/src/hooks/useLiveAudio.ts` · `components/LiveInterview.tsx` | Captura y UI del modo en vivo |
| `e2e/` | E2E del modo en vivo (Playwright, audio falso) |
| `mcp/` | Servidor MCP `careerai-mcp` |
| `docs/reviews/c2-d2-cto-review.md` | Dictamen del deploy del modo en vivo (D-2) |
| `Dockerfile` · `heroku.yml` | Imagen y manifiesto de Heroku |

---

## 9. Variables de entorno (solo placeholders — repo público)

```bash
# Runtime: Heroku Config Vars (o .env local, gitignored)
GEMINI_API_KEY=<Heroku Config Vars>
GEMINI_MODEL=gemini-3.1-flash-lite
DEEPGRAM_API_KEY=<Heroku Config Vars>
CORS_ORIGINS="https://career-ai-95daf7c9a813.herokuapp.com,http://localhost:5173"
CV_OUTPUT_DIR=/tmp/cvs

# Build: heroku.yml → build.config
VITE_API_URL=https://career-ai-95daf7c9a813.herokuapp.com
```

---

## 10. Próxima sesión — cola

1. **Ciclo del copiloto para llamadas fluidas** (`brainstorm → design-spec`)
   con los hallazgos del 13 oct (§2): voces separadas, muletillas, regla de
   perspectiva, pistas cortas visibles y sugerencia especulativa. Antes,
   revisar en `heroku logs` si las keyterms llegan a Deepgram.
2. **Perfil maestro:** sumar los repos nuevos que Jonathan compartió
   (`pcre-learning-platform`, `outlet-sourcing`, `mono-rooftop`) y precisar
   el estado de su formación en ingeniería de datos. Vive fuera del repo
   (Proyecto de claude.ai).
3. **Skills del flujo:** `ci-cd`, `agent-evals` e `independent-review`,
   destiladas del trabajo real (prompt listo fuera del repo).
4. **Radar de vacantes:** sigue los lunes hasta el 26 oct; el detalle vive
   fuera del repo. La métrica es a cuáles aplica Jonathan.
5. **Ciclo #3:** perfil verificable con login de GitHub.

---

*Última actualización: 13 oct 2026. v1.2 desplegada (`0b10c01`) y probada en
una entrevista real; sus hallazgos quedan en §2 y en la cola.*
*Siguiente actualización: al abrir el ciclo del copiloto para llamadas
fluidas.*
