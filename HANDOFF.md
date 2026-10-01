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
  desde el 1 oct 2026 (D-2: `ee9fef0`, desplegado por Jonathan). H-2 y
  H-MCP hechos. Falta H-3 (prueba humana en Meet,
  `docs/reviews/h3-guion-meet.md`) y la calibración que salga de ella.

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
- **Calibración pendiente del modo en vivo:** `TURN_CONTINUATION_S` (1.5 s)
  y `STT_ENDPOINTING_MS` (100) se ajustan con H-3. En modo micrófono la voz
  del candidato también entra y puede reiniciar sugerencias.
- **Hallazgo de H-2: un monólogo se vuelve un solo turno.** La continuación
  v1.1 encadena sin tope: si quien habla nunca calla 1.5 s, el turno crece
  (hasta 4000 caracteres), la tarjeta muestra todo el párrafo como
  "pregunta" y la sugerencia se reinicia en cada cierre. En una entrevista
  normal, el silencio mientras respondes cierra el turno; el riesgo es una
  presentación larga del entrevistador antes de preguntar. Propuesta para
  la enmienda v1.2 de REQ-04: continuar solo mientras el turno acumulado
  sea corto (los cortes reales de Nova-3 tienen 1–5 palabras; ver PR #18).
  La puntuación no sirve como señal: Nova-3 escribió "¿Cómo manejarías?" en
  un corte. Toca `turn_detector.py` (zona congelada): espera H-3 y el OK de
  Jonathan.
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

1. **H-3:** prueba humana en Meet con `docs/reviews/h3-guion-meet.md`
   (ronda con la pestaña y ronda con el micrófono). Trae los dos
   resúmenes, la tabla de anotación, el video y el log.
2. **Calibración** con H-3: `TURN_CONTINUATION_S`, `STT_ENDPOINTING_MS`, el
   modo micrófono y la enmienda v1.2 de REQ-04 (tope a la continuación,
   hallazgo de H-2). Necesita el OK de Jonathan (zona congelada).
3. **Deepgram:** confirmar que Auto-reload está apagado (el saldo prepagado
   es el tope de gasto).
4. **Radar de vacantes:** semana 1 entregada (QAD/Redzone, breakmark y
   Capgemini). La métrica es a cuáles aplica Jonathan.
5. **Ciclo #3:** perfil verificable con login de GitHub
   (`brainstorm → design-spec`).

---

*Última actualización: 1 oct 2026. D-2 desplegado (`ee9fef0`), H-2 y H-MCP
hechos; el README del MCP corrige el orden de `claude mcp add`.*
*Siguiente actualización: tras H-3.*
