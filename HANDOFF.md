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
- **Fase actual:** Ciclo #1 (Heroku + SDK de Gemini) **CERRADO** el 29 sep
  2026. Ciclo #2 (copiloto en tiempo real): spec y plan **APROBADOS**
  (`C2-SPEC-01`, `C2-PLAN-01`), en ejecución.

---

## 2. Estado real

### ✅ Funcionando (verificado en producción, 28–29 sep 2026)

| Feature | Evidencia |
|---|---|
| CV Engine (keywords → score → PDF) | `POST /api/cv/generate` 200 en ~2 s; PDF 200 (logs de Heroku) |
| Plantilla de CV de una columna, skills por grupos, viñetas limpias | PR #3 + suite pytest |
| Download PDF | Funciona en Heroku: el archivo se descarga al momento, antes del ciclo diario del dyno |
| Print to PDF | `f8c228b` |
| Copilot de texto → SSE (`meta → chunk* → error? → done`) | 942 ms, captura del E2E |
| 429 de Gemini → evento SSE `rate_limit`; stream fuera del event loop | `6e74e4f` + prueba offline 8/8 |
| CORS por variable de entorno | original |

### ❌ Conocidamente roto (se resuelve en el Ciclo #2)

| Issue | Causa | Decisión |
|---|---|---|
| Audio (grabar → Stop) no transcribe | Desde `24d3ce1`: `handleAudioStop` cierra el WebSocket antes de que `MediaRecorder` entregue el audio, y se descarta | Ratificado el 29 sep: se reemplaza por streaming en el Ciclo #2 |
| El audio es solo en español y solo del micrófono | `language="es"` fijo; `getUserMedia` | Ciclo #2: pestaña de la reunión + inglés/español |
| Sin contexto, las sugerencias inventan historias y métricas | No existe Context Bridge | Ciclo #2: REQ-05/REQ-06 |

### ⚠️ Deuda técnica vigente

- **El CV Engine bloquea el event loop.** Hace llamadas síncronas a Gemini y
  a WeasyPrint dentro de rutas `async`, así que cada CV congela el servidor
  unos segundos. Con usuarios concurrentes, sprint dedicado.
- **Sin timeouts en Gemini ni Deepgram** (regla 6). El Ciclo #2 los agrega
  al copiloto.
- **Demo pública sin límite de peticiones.** La key de Gemini tiene billing
  con tope; hace falta un rate limit antes de difundir la URL.
- **Sin CI ni protección de `main`.** La CI entra en el Ciclo #2 (primer
  change set).
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
    └── uvicorn app.main:app --host 0.0.0.0 --port $PORT   (heroku.yml → run.web)
        ├── /api/cv/generate · /api/cv/{archivo}/pdf
        ├── /api/interview/text        → SSE (Gemini)
        ├── /api/interview/ws/audio    → WS pre-grabado (roto; se reemplaza en C2)
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

---

## 5. Estrategia comercial — fuera del repo

El mapa competitivo, el posicionamiento y el pricing viven en `strategy.md`,
un documento privado del Proyecto career-ai en Claude. Ningún análisis de
competidores, precio objetivo ni estrategia de go-to-market entra a este
repo; los specs lo referencian sin copiarlo.

---

## 6. Roadmap

1. **Ciclo #2 — Copiloto en tiempo real** (`docs/specs/copiloto-tiempo-real.md`,
   aprobado el 29 sep 2026):
   - Escucha la pestaña de la reunión y transcribe en streaming en
     inglés/español.
   - Detecta preguntas y sugiere sin clics.
   - Context Bridge + regla anti-invención.
   - Modo entrevista y resumen de sesión.
   - Validación de Origin, límites, timeouts y CI.
2. **Ciclo #3 — CV Builder v2:**
   - Importar el CV en PDF y editar en campos estructurados.
   - Secciones nuevas: Proyectos, Idiomas, Certificaciones y tecnologías por
     puesto.
   - Confirmar la experiencia real antes de agregar cada palabra clave.
   - El "ATS %" pasa a llamarse "coincidencia con la vacante".
3. **Practice Mode:** simulador de entrevistas con reclutador IA, derivado de
   la skill `ai-recruiter-interview-coach` y de las métricas de las primeras
   sesiones reales.
4. **Phase 3:** auth + base de datos + pagos.
5. **Deuda:** event loop del CV Engine, rate limit, protección de `main`.

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
| `backend/app/services/stt_client.py` | Deepgram (pre-grabado; se reemplaza en C2) |
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

1. Ejecutar el plan del Ciclo #2 change set por change set.
2. E2E humano del Ciclo #2 en una reunión real de Meet (guion de 10
   preguntas).
3. Ciclo #3 — CV Builder v2 (`brainstorm → design-spec`).

---

*Última actualización: 29 sep 2026 — cierre del Ciclo #1 (Heroku + SDK de
Gemini), hotfix del formato del CV, C2-SPEC-01 aprobado.*
*Siguiente actualización: al cerrar el Ciclo #2.*
