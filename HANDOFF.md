# HANDOFF.md — CareerAI
> Fuente de verdad para cualquier agente (Fable/Opus/Sonnet) que tome este proyecto.
> Sobrescribir al cerrar cada fase. NO acumular.

---

## 1. Identidad del Proyecto

**Producto:** CareerAI — ATS Optimizer + Real-Time Interview Copilot
**Repo:** https://github.com/astraDukoWave/career-ai — **PÚBLICO** (decisión cerrada, ver sección 4)
**Prod URL:** https://career-ai-astradukowave.replit.app *(ZOMBIE: trial vencido y suscripción cancelada — responde 200 de prestado, puede caer sin aviso; cutover URGENTE, ver §3)*
**Health check:** `GET /health → {"status": "ok"}`
**Stack:** FastAPI + Gemini 2.5 Flash + Deepgram Nova-3 + React/Vite + WeasyPrint
**Fase actual:** Phase 0 (MVP) — CERRADO · Limpieza de repo ejecutada (rama `chore/phase-0-closure`)
**Próxima fase:** Migración a Heroku (ciclo SDD #1) → Phase 1A Context Bridge → Practice Mode

---

## 2. Estado Real del MVP (Phase 0)

### ✅ Funcionando y verificado en producción

| Feature | Descripción | Commit(s) |
|---|---|---|
| CV Engine | Job posting → ATS score → CV tailored → HTML preview | original |
| ATS Scoring | Keyword extraction (Gemini) + substring match + synonyms | original |
| LLM Bullet Rewrite | Opcional, no fuerza métricas artificiales | 08157aa |
| Print to PDF | `window.open()` nueva ventana, no iframe sandbox | f8c228b |
| Interview Copilot | Texto → SSE streaming → STAR/ELI5/Code suggestion | original |
| Intent Detection | behavioral_star / tech_code / tech_concept (keyword-based) | original |
| Language Detection | ES/EN automático por stopwords | original |
| Audio STT | MediaRecorder → blob completo al Stop → Deepgram pre-recorded | 24d3ce1 |
| CORS | Env-driven (`Settings.cors_origins_list`), nunca hardcoded | original |
| Replit Deploy | Autoscale 2vCPU/4GB, FastAPI sirve frontend build estático | Perplexity |

### ❌ Conocidamente roto

| Issue | Causa | Decisión |
|---|---|---|
| Download PDF button | WeasyPrint genera el archivo pero el serve falla por volumen efímero de Replit | **Eliminar el botón en Phase 1B** (Print to PDF verde es el camino oficial; un botón roto en demo cuesta más que su ausencia) |
| Audio pre-recorded latencia 1-2s | Pre-recorded API, no Live Streaming | Aceptable — no tocar |
| Audio en Safari/mobile | MediaRecorder emite MP4, no WebM — Deepgram rechaza | Chrome desktop required — documentar en UI si hay tiempo en 1B |

### ⚠️ Deuda técnica vigente

- `client.listen.v1.media.transcribe_file` en `stt_client.py` — sintaxis "revertida" que funciona pero NO es la documentación oficial de Deepgram v7. Frágil ante actualizaciones del SDK. No tocar sin sprint dedicado.
- PostgreSQL y Redis provisionados (docker-compose + Replit secrets) pero **NO conectados** — cero psycopg2 en requirements.txt. Se activan en Phase 3.
- `frontend/src/hooks/useAudioCapture.ts` conserva framing obsoleto de
  chunks (~timesliceMs, opción sin uso, comentario de "cadence") en líneas
  ~14-19. Solo comentarios y una opción muerta — corregir en Phase 1B.

*(Deuda resuelta en limpieza Jul 2026: `skill-creator-v2.md` eliminado, `sedoU0aHS` eliminado, STATE.md y README.md actualizados, comentario obsoleto de chunks en `interview_audio.py` corregido.)*

---

## 3. Arquitectura Actual (producción en Replit)

```
Replit Autoscale (puerto 5000)
└── FastAPI (backend/)
    ├── /api/cv/generate  → CV Engine → WeasyPrint → PDF en /tmp/cvs/
    ├── /api/cv/{id}/pdf  → FileResponse (volumen efímero en Replit)
    ├── /api/interview/text → SSE stream (Gemini)
    ├── /api/interview/ws/audio → WebSocket → Deepgram pre-recorded
    ├── /health
    └── /* → StaticFiles(frontend/dist/)  ← frontend React built en deploy

Build pipeline (.replit):
  cd frontend && npm install && npm run build
  cd backend && pip install -r requirements.txt
  uvicorn app.main:app --host 0.0.0.0 --port 5000
```

**DECISIÓN ACTUALIZADA (14 Jul 2026): migración aprobada a Heroku.**
El trigger de costos previsto en esta sección se activó: Replit requiere
suscripción (~$240/año) mientras el GitHub Student Pack cubre Heroku con
$13/mes × 24 meses ($312 — alcanza para un Basic dyno de $7 que no duerme).
Decisión: **lift-and-shift del MONOLITO** (sin split Vercel) a Heroku vía
container — `backend/Dockerfile` ya instala las libs nativas de WeasyPrint
(pango/cairo/gdk-pixbuf) y CORS/URLs son env-driven, así que la app NO
requiere cambios de código; solo cambian pipeline de deploy y secrets.

- Estado real (verificado 14 Jul 2026 vía `/health` → 200): el trial de
  Replit EXPIRÓ y la suscripción está cancelada, pero el deployment sigue
  respondiendo — **vive de prestado y puede caer sin aviso.** NO tocar nada
  de Replit (ni `.replit`/`replit.nix`, ni redeploys) hasta que el E2E pase
  en Heroku. Cutover: **esta semana.**
- La migración se ejecuta como el PRIMER ciclo SDD completo (design-spec →
  design-plan → execute → verify). **E2E del cutover:** `/health` 200 +
  CV generado con ATS score + SSE del copilot + audio WS, todo en el
  dominio nuevo de Heroku.
- Vercel descartado para el backend: sin libs nativas del sistema, sin
  WebSockets, sin proceso persistente. El split frontend/backend agrega
  complejidad (CORS, doble deploy) sin ganancia a esta escala.
- Plan B documentado: DigitalOcean App Platform ($200 de crédito
  estudiantil, 12 meses, canjear antes del 2026-07-31).

---

## 4. Decisiones Técnicas Cerradas (no reabrir sin justificación)

| Decisión | Elegido | Razón |
|---|---|---|
| LLM | Gemini 2.5 Flash | 1500 RPD free, baja latencia |
| STT | Deepgram Nova-3 pre-recorded | Funciona con MediaRecorder WebM completo |
| PDF | WeasyPrint → Print to PDF nativo | Print to PDF es más confiable en producción |
| Intent routing | Keyword-based (no LLM) | <10ms vs 500-1500ms de round-trip |
| CORS | Env-driven, NUNCA `allow_origins=["*"]` con credentials | Spec HTTP lo prohíbe |
| Auth | Sin auth (hasta Phase 3) | PostgreSQL/Redis listos pero inactivos |
| STT mode | Pre-recorded (no Live Streaming) | Live Streaming es v3 — callbacks complejos |
| **Deploy producción** | **Heroku Basic dyno (container)** | Trigger de costos activado; crédito estudiantil 24 meses; monolito sin split; Replit operativo hasta el cutover (14 Jul 2026) |
| **Visibilidad del repo** | **Público** | Portfolio verificable para búsqueda de empleo; riesgos auditados y mitigados (Jul 2026) |
| **Política de secretos** | **Placeholders en docs y código; valores reales SOLO en Replit Secrets / .env local (gitignored)** | El repo es público; un secreto commiteado vive para siempre en el historial (Jul 2026) |

---

## 5. Estrategia Comercial — MOVIDA FUERA DEL REPO

El mapa competitivo, el análisis de mercado y el pricing NO se versionan en
este repositorio porque es público. Viven en `strategy.md`, documento privado
en el **Proyecto A (career-ai) de Claude App**.

Regla: ningún análisis de competidores, precios objetivo, o estrategia de
go-to-market entra a este repo. Si un spec necesita ese contexto, se referencia
("ver strategy.md") sin copiarlo.

---

## 6. Roadmap Fase 1+

### Ciclo SDD #1 — Migración del monolito a Heroku (antes de 1A)

Decisión y E2E en §3. Alcance: pipeline de deploy + secrets + dominio;
**cero cambios de código de la app.** Usar skill `system-design-spec`
(regla 3: protocolos WS/SSE; regla 6: timeouts en llamadas externas).
Al pasar verify: cutover, retirar `.replit`/`replit.nix`, actualizar URLs
en README/CLAUDE.md/§9, y cancelar/no renovar Replit.

### Phase 1A — Context Bridge · ciclo SDD #2 (1 semana, ~50 líneas, impacto máximo)

**Problema:** Interview Copilot responde genéricamente. No sabe qué vacante generaste ni tu experiencia.

**Solución:** Pasar `job_title`, `matched_keywords`, y resumen de experiencia del CV Engine al system prompt del Copilot.

**Spec:**
- Cuando `CVGenerator.tsx` recibe `CVResponse`, guardar en React context/localStorage: `{job_title, skills, matched_keywords, experience_summary}`
- `InterviewCopilot.tsx` lee ese contexto al montar
- Nuevo field en `InterviewTextRequest`: `context?: {job_title: string, skills: string[], experience_summary: string}`
- `llm_client.py`: inyectar context en `_SUGGESTION_BASE_PROMPT` antes de generar

**Definition of done:**
- [ ] El copilot menciona la vacante específica en su respuesta
- [ ] El copilot referencia bullets de la experiencia del usuario
- [ ] Sin cambios de esquema de DB (todo en frontend state)

**Nota estratégica:** 1A es prerequisito duro de Practice Mode — sin el puente
JD→Copilot, el simulador no sabe sobre qué vacante preguntar.

### Phase 1B — UX Audio + limpieza de demo (3 días)

- Estado "Processing..." visible tras Stop
- Label STAR/ELI5/Code más prominente
- Indicar que se transcribe al Stop (no en tiempo real)
- **Eliminar el botón Download PDF roto** (ver sección 2)

### Phase 2 — Practice Mode / Simulador de AI Recruiter (2 semanas)

**Upgrade Jul 2026:** el spec de dominio ya NO se inventa — se deriva de la
skill `ai-recruiter-interview-coach`, construida a partir de 3 entrevistas
reales con reclutadores IA (micro1/Zara). El producto invierte el rol de la
skill: CareerAI juega a Zara. Mapeo directo:

- Tabla de calibración por seniority (skill §4) → el generador ajusta la dificultad de preguntas según la vacante
- Encadenamiento con glosario de decisiones (skill §5) → las preguntas construyen sobre respuestas previas del usuario, no son sueltas
- Modos A/B/C (skill §1) → tipos de pregunta del simulador (rapport / técnica encadenada / coding)
- Detección de pistas de rúbrica (skill §3) → motor de scoring: ¿la respuesta cubrió los conceptos esperados?

Cambia retention: de "herramienta del día de la entrevista" a "herramienta
para prepararse la semana antes".

**Alineación a hackathon:** AI Infra Summit Hackathon (lablab.ai),
**Sep 15–17 2026**, participación online, solo. Tracks de sponsors se anuncian
~agosto → mantener capa de adaptación abierta; no congelar la feature del
hackathon antes de conocer los stacks patrocinados. Criterios de evaluación:
Application of Technology, Presentation, Business Value, Originality.
Regla de solo-builder: el último 20% del timeline se reserva a demo y pitch.

### Phase 3 — Auth + Freemium (1 mes)

- Activar PostgreSQL (Supabase recomendado — compatible con MCP de Claude Code)
- JWT auth
- Freemium → paywall (detalles de pricing en strategy.md)

---

## 7. Metodología de Trabajo (AI-Native Stack)

### Capas del sistema

```
Strategic Layer (Claude App / Fable)
  └── Skills: brainstorm → design-spec → design-plan → verify
  └── Produce: spec.md + plan.md por feature (ENTREGA archivos; el humano commitea)

Knowledge Layer (Notion + skills de dominio)
  └── RAGs por curso en Notion (capa profunda, pull — se consulta)
  └── Skills por paso del ciclo (capa delgada, push — se disparan solas)
  └── Primera: system-design-spec, destilada del RAG "Backend System Design — Jem Young"
      ⚠️ Requiere que la página Engineering Knowledge Base esté compartida con la conexión de Claude
  └── Claude Code CLI no ve Notion → design-plan pega las reglas extraídas dentro del plan.md

Execution Layer (Claude Code CLI / Sonnet)
  └── Lee: HANDOFF.md + STATE.md + el plan.md del feature
  └── Ejecuta: código, tests, commit, PUSH A RAMA NUEVA (obligatorio, siempre)
  └── .claude/skills/: harness-engineering (fuente: workflow BetSync verificado + curso)
  └── Docker/stack corriendo → SIEMPRE Codespaces con prompt aparte (MacBook Air 2017 sin Docker)

Infrastructure Layer (MCP)
  └── Supabase (cuando se active PostgreSQL en Phase 3)
  └── GitHub (PRs, commits — vía instancia con MCP de escritura)
```

### Ciclo por feature (Spec-Driven Development)

```
1. BRAINSTORM  → Claude App pregunta aclaratorias, elimina ambigüedad
2. DESIGN SPEC → Claude App genera spec.md → humano aprueba → humano commitea a docs/specs/
3. DESIGN PLAN → Claude App desglosa en tasks → humano aprueba → humano commitea a docs/plans/
4. EXECUTE     → Sonnet (Claude Code CLI) implementa task por task, en rama nueva, con push
5. VERIFY      → Claude App audita diff (tarball codeload) vs spec; tests corren en CLI/Codespaces
6. MERGE       → PR con descripción del spec completado; merge tras luz verde del CTO
```

### Reglas fijas (aprendidas con sangre en BetSync)

- Todo prompt a agente local termina en **commit + push a rama nueva**. Falló dos veces sin esta regla.
- Ningún reporte de "listo/mergeado/verificado" se acepta sin re-verificación independiente contra el repo real.
- Claims etiquetados: `[verified-this-session]` / `[inherited-unverified]` / `[contradicted]`.
- Regla anti-loop: si Claude + un segundo agente ya coincidieron → ejecutar sin más auditorías. Si una decisión está en este HANDOFF como "cerrada" → NO reabrir.

---

## 8. Archivos Clave

| Archivo | Propósito | Estado |
|---|---|---|
| `HANDOFF.md` | Este archivo — fuente de verdad entre fases | ✅ Activo (v2, Jul 2026) |
| `STATE.md` | Sprint activo, bloqueantes | ✅ Actualizado en limpieza |
| `README.md` | Cara pública del repo — portfolio-facing | ✅ Reescrito en limpieza |
| `CLAUDE.md` | Contexto para Claude Code CLI | ✅ Ampliado en limpieza |
| `docs/specs/` · `docs/plans/` | Specs y planes por feature (SDD) | ✅ Creados, vacíos |
| `.claude/skills/` | Skills de capa de ejecución (harness-engineering primero) | ⏳ Post-limpieza |
| `strategy.md` | Competencia + pricing | 🔒 PRIVADO — Proyecto A Claude App, NO en repo |
| `backend/app/services/stt_client.py` | Deepgram integration | Funciona, syntax frágil |
| `backend/app/services/llm_client.py` | Gemini + prompts | ✅ Limpio |
| `frontend/src/components/CVPreview.tsx` | CV preview + Print to PDF | ✅ new window approach |

---

## 9. Variables de Entorno Requeridas

Valores reales SOLO en Replit Secrets (producción) o `.env` local (gitignored).
Este archivo es público: solo placeholders.
Tras el cutover a Heroku, `CORS_ORIGINS` y `VITE_API_URL` cambian al dominio nuevo.

```bash
# Backend
GEMINI_API_KEY=<Replit Secrets>
GEMINI_MODEL=gemini-2.5-flash
DEEPGRAM_API_KEY=<Replit Secrets — rotada Jul 2026>
CORS_ORIGINS="https://career-ai-astradukowave.replit.app,http://localhost:5173"
CV_OUTPUT_DIR=/tmp/cvs

# Frontend (Vite build time)
VITE_API_URL=https://career-ai-astradukowave.replit.app
```

---

## 10. Próxima Sesión — Cola de Arranque

Pegar esto en la siguiente ventana de Claude (Fable):

```
Lee HANDOFF.md en la raíz del repo antes de hacer cualquier cosa.

Contexto: CareerAI, Phase 0 cerrado, limpieza de repo hecha. Cola en orden:

1. Crear .claude/skills/harness-engineering/
   Fuentes: workflow-multiagente-betsync.md (prácticas verificadas) +
   curso learn-harness-engineering (init phase, feature_list.json, no
   declarar victoria antes de e2e).

2. ✅ HECHO (13 Jul 2026) — skill system-design-spec destilada del RAG
   real (14 lecciones, query SQL) e instalada en Claude App.

3. Ciclo SDD #1 — URGENTE (producción zombie, puede caer sin aviso):
   /design-spec Migración del monolito a Heroku.
   Ver §3 (decisión + E2E) y §6. Crédito Heroku: ✅ canjeado (14 Jul).
   DO (plan B): pendiente — reintentar canje antes del 2026-07-31.

4. Ciclo SDD #2: Phase 1A Context Bridge (spec semi-listo en §6).

5. /brainstorm Practice Mode — simulador de AI recruiter
   (spec de dominio: skill ai-recruiter-interview-coach; prerequisito
   técnico: Phase 1A Context Bridge).
```

---

*Última actualización: 14 Jul 2026 — Auditoría Fable + cierre de limpieza Phase 0 + migración a Heroku aprobada*
*Siguiente actualización: al cerrar Phase 1A (Context Bridge)*
