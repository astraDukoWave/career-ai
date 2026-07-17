# Spec: migracion-monolito-heroku

> Ciclo SDD #1 · URGENTE (producción zombie, HANDOFF §3)
> Skills: `design-spec` + `system-design-spec` (reglas 0, 3, 6, 7, 8, 10)
> Estado: **APROBADO** por CTO (15 Jul 2026) con revisión de segunda instancia.
> Destino: `docs/specs/migracion-monolito-heroku.md`

---

## Resumen General

Lift-and-shift del monolito FastAPI + React desde el deployment zombie de
Replit a un Basic dyno de Heroku vía container stack. Cambian únicamente el
pipeline de deploy y la gestión de secrets; **cero cambios de código de la
app** (`backend/app/**` y `frontend/src/**` intocables).

## Objetivos del Usuario

- Como builder, quiero producción sobre infraestructura pagada con el crédito
  estudiantil, para que la demo y el portfolio no dependan de un deployment
  que puede caer sin aviso.
- Como usuario final, quiero que el flujo completo (CV → ATS score → copilot
  texto y audio) funcione idéntico en el dominio nuevo.
- Como candidato en búsqueda activa, quiero una URL de producción estable
  para compartir en aplicaciones y entrevistas.

## Alcance Estricto v1

### Incluye:
- App Heroku nueva: stack `container`, región `us`, un solo proceso `web` en
  Basic dyno.
- `heroku.yml` en la raíz del repo + Dockerfile de deploy nuevo en la raíz
  (multi-stage: build del frontend + runtime Python con las libs nativas de
  WeasyPrint ya probadas en `backend/Dockerfile`).
- Config vars de runtime (secrets) + variable de build para el frontend.
- Verificación E2E completa en el dominio nuevo (sección final).
- Cutover post-verify: actualización de URLs en docs, retiro de
  `.replit`/`replit.nix`, Replit queda sin reactivar.

### NO incluye:
- Cambios en `backend/app/**` o `frontend/src/**` — regla dura del ciclo.
- Split frontend/backend (Vercel descartado — decisión cerrada, HANDOFF §3/§4).
- Timeouts de aplicación en llamadas a Gemini/Deepgram (deuda registrada;
  candidata a 1B o sprint dedicado).
- Validación de `Origin` en el handshake del WS (TODO documentado en
  `interview_audio.py`; entra con auth en Phase 3).
- Flag de opt-out del LLM rewrite en `CVRequest` (ver EDGE-05 — sprint
  dedicado si el peor caso lo exige).
- GitHub auto-deploy, pipelines, review apps, custom domain (v2).
- Fix del botón Download PDF — sigue roto igual que en Replit (filesystem
  efímero en ambas plataformas); se elimina en 1B como ya está decidido.
- PostgreSQL/Redis (Phase 3).

## Contexto de plataforma — hechos verificados que gobiernan el spec

| # | Hecho | Fuente |
|---|---|---|
| P1 | Ventana inicial de 30 s para que el proceso web devuelva datos (H12); después, cada byte en cualquier dirección resetea una ventana rodante de 55 s; sin datos en esa ventana, la conexión se corta con H15 o H28 | Dev Center · HTTP Routing / Request Timeout |
| P2 | La capa de routing monitorea las conexiones WebSocket verificando que pase algún dato al menos cada 55 s — los pings de protocolo cuentan como tráfico | Heroku Help |
| P3 | El contexto de build es el directorio del Dockerfile y no es configurable; `build.config` define variables de build-time que deben corresponder a un `ARG` del Dockerfile y no crean config vars de runtime — y las config vars de runtime no están disponibles en build; sin sección `run`, se usa el CMD del Dockerfile | Dev Center · heroku.yml |
| P4 | Con el stack en `container` y heroku.yml referenciando el Dockerfile, `git push heroku` construye la imagen en Heroku → no se requiere Docker local (restricción MacBook Air resuelta; Codespaces queda como plan B de build) | Changelog Heroku |
| P5 | Basic dyno: $7/mes como máximo corriendo 24/7, 512 MB de RAM, no duerme; máximo un dyno corriendo por process type | Heroku Help / Dev Center |
| P6 | El proceso web debe bindear a $PORT en 60 s; en restarts hay 30 s tras SIGTERM antes del SIGKILL; R15 si un basic alcanza 1 GB (2× su cuota); imágenes OCI hasta 5 GB y más de 40 layers pueden fallar el boot | Dev Center · Limits |
| P7 | uvicorn 0.32.1 (versión pineada): `--ws-ping-interval` default 20 s — dentro de la ventana de 55 s de P2. Verificado contra el binario instalado (15 Jul 2026) | requirements.txt + CLI |
| P8 | `main.py` resuelve el frontend como `parents[2]/frontend/dist` desde su propia ruta y solo monta StaticFiles si el directorio existe → el layout de la imagen debe replicar la relación `<raíz>/backend/app/` ↔ `<raíz>/frontend/dist` | repo, verificado |
| P9 | `client.ts` e `InterviewCopilot.tsx` leen `VITE_API_URL` en build-time con fallback `http://localhost:8000`; el WS deriva `wss://` del replace `http→ws` sobre esa misma variable | repo, verificado |

## Requisitos

- **REQ-01** — App Heroku creada con stack `container`, región `us`, proceso
  único `web` en Basic dyno. Nombre objetivo `career-ai`; el dominio real
  asignado se registra como fuente de verdad (ver EDGE-01).
- **REQ-02** — `heroku.yml` en la raíz del repo, referenciando un
  **Dockerfile de deploy nuevo en la raíz** (consecuencia directa de P3:
  desde `backend/` el contexto no alcanza `frontend/`). `backend/Dockerfile`
  y `frontend/Dockerfile` siguen siendo los de docker-compose local; la
  duplicación de la capa de libs nativas es un trade-off aceptado en v1.
  **Guardia de drift:** ambos Dockerfiles (el de raíz y `backend/Dockerfile`)
  llevan un comentario cruzado que remite al otro archivo y exige que
  cualquier cambio en la lista de libs nativas de WeasyPrint se replique en
  ambos. El comentario en `backend/Dockerfile` es la única edición permitida
  a ese archivo en este ciclo.
- **REQ-03** — El Dockerfile de deploy es multi-stage: una etapa Node 20
  construye `frontend/dist` recibiendo `VITE_API_URL` como `ARG` (inyectado
  vía `build.config`, por P3); la etapa final parte de `python:3.11-slim`,
  instala exactamente las libs nativas de WeasyPrint ya probadas en
  `backend/Dockerfile` (pango, pangoft2, cairo, gdk-pixbuf, libffi,
  shared-mime-info, fuentes DejaVu) y los requirements pineados.
- **REQ-04** — El layout interno de la imagen preserva la relación de P8, de
  modo que StaticFiles monte sin tocar `main.py`.
- **REQ-05** — El comando de arranque vive en la sección `run` de
  `heroku.yml` (única fuente de verdad del boot) y bindea uvicorn a `$PORT`
  con host `0.0.0.0`. El CMD del `backend/Dockerfile` (puerto 8000
  hardcodeado) no participa del deploy.
- **REQ-06** — Config vars de runtime en Heroku: `GEMINI_API_KEY`,
  `GEMINI_MODEL`, `DEEPGRAM_API_KEY` (la rotada en Jul 2026),
  `CORS_ORIGINS` (dominio Heroku + `http://localhost:5173`),
  `CV_OUTPUT_DIR=/tmp/cvs`. Política de secretos vigente: valores reales
  solo en Heroku Config Vars / `.env` local; placeholders en docs (repo
  público, HANDOFF §4).
- **REQ-07** — Orden de operaciones obligatorio por P3 (las runtime vars no
  existen en build): crear app → registrar dominio asignado → fijar
  `VITE_API_URL` con ese dominio en `build.config` → push.
- **REQ-08** — Replit intocable hasta verify verde: ni redeploys, ni edición
  de `.replit`/`replit.nix`, ni cambios de secrets allí (HANDOFF §3).
- **REQ-09** — Cutover post-verify: actualizar URLs en `README.md`,
  `CLAUDE.md` y HANDOFF §1/§9 (incluida la corrección del puerto
  contradicho: §3 dice 5000, `.replit` corre 5173), eliminar `.replit` y
  `replit.nix`, y dejar constancia de no reactivar Replit.
- **REQ-10** — Todo el trabajo en rama nueva (`chore/heroku-migration`) con
  push; merge solo tras verify (regla fija, HANDOFF §7).

## Requisitos no funcionales (reglas 3, 6, 7 y 8 de system-design-spec)

- **NFR-01 · SSE** — `/api/interview/text` debe emitir su primer byte en
  < 30 s (P1). Latencia real del primer chunk de Gemini:
  [inherited-unverified], el E2E la mide. Los gaps entre chunks quedan muy
  por debajo de 55 s en streaming normal; el cliente ya maneja el cierre sin
  `done` (verificado en `client.ts`).
- **NFR-02 · WS audio** — Socket ocioso durante la grabación (blob único al
  Stop, `recorder.start()` sin timeslice — verificado). Supervivencia
  sostenida por los pings de 20 s de uvicorn (P7) dentro de la ventana de P2.
  **Hipótesis, no garantía**: se confirma con grabación > 90 s en el E2E
  (AC-06).
- **NFR-03 · CV generate** — Respuesta completa en < 30 s o el router corta
  con H12 mientras el dyno sigue trabajando (P1). El peor caso es el camino
  del rewrite, que se dispara **automáticamente** cuando el score inicial es
  < 0.60 (umbral en `cv_engine.py`, verificado — no existe flag en el
  request). El E2E fuerza ese camino con un input de bajo fit deliberado.
  Si excede: decisión explícita antes de merge, nunca parche silencioso.
- **NFR-04 · Memoria** — Cuota de 512 MB; WeasyPrint es el pico esperado.
  Observar R14/R15 en logs durante todo el E2E. Trigger futuro (regla 8,
  escalera de escalado): R14 recurrente en uso normal → Standard-1X; no
  antes, no por precaución.
- **NFR-05 · CAP (regla 7)** — Se elige disponibilidad: app stateless sin
  DB; el ciclado del dyno (P6) pierde conexiones vivas y borra `/tmp` —
  aceptado, el usuario reintenta y no hay estado que corromper. Es el mismo
  modelo efímero de Replit.
- **NFR-06 · TLS** — `*.herokuapp.com` sirve HTTPS por defecto; `wss://` se
  deriva correctamente por P9. Regla 9 aplicable en su mitad de transporte;
  authn/authz siguen fuera hasta Phase 3.

## Comportamiento Esperado

### Flujo feliz (pipeline de cutover):
1. Crear la app (stack container, región us) y registrar el dominio asignado.
2. Fijar config vars de runtime (REQ-06) y `VITE_API_URL` de build (REQ-07).
3. Commit de `heroku.yml` + Dockerfile de deploy en `chore/heroku-migration`,
   push a GitHub.
4. Push al remote de Heroku → build remoto multi-stage → release → dyno arriba.
5. `/health` responde 200 en el dominio nuevo.
6. E2E completo (sección final) con logs en vivo.
7. Verify (skill `verify`, diff vs este spec) → cutover REQ-09 → PR y merge.

### Casos edge:
- **EDGE-01** — Nombre `career-ai` ocupado → variante (p. ej.
  `career-ai-adw`); el dominio registrado tras el create es la fuente de
  verdad para REQ-06/07 y docs.
- **EDGE-02** — Grabación > 90 s y el WS muere (H15) pese a los pings → se
  registra como limitación conocida con nota de UX (grabaciones cortas) e
  issue dirigido a Phase 1B, que ya toca audio UX. No se parchea código en
  este ciclo.
- **EDGE-03** — `frontend/dist` ausente o mal ubicado en la imagen → API
  viva pero `/` devuelve 404 (StaticFiles solo monta si el dir existe, P8).
  Cubierto por AC-02.
- **EDGE-04** — Build sin `VITE_API_URL` → el bundle cae en silencio al
  fallback `localhost:8000` (P9) y la app queda rota solo en runtime.
  Cubierto por AC-07.
- **EDGE-05** — CV generate > 30 s → H12: el usuario ve el error del
  `ApiError`, el dyno sigue procesando sin saberlo (P1). Contexto verificado:
  el rewrite NO es opcional por request — se dispara automáticamente con
  score inicial < 0.60; no hay flag en `CVRequest` ni en el frontend.
  **Workaround sin código (operativo):** el peor caso solo ocurre en el
  camino de bajo fit; para demos y uso normal se documenta que inputs con
  fit razonable (score ≥ 0.60) evitan por completo el camino del rewrite.
  Si el E2E muestra H12 en el camino forzado: se documenta la limitación y
  el fix real (flag de opt-out en el request + timeout de aplicación) va a
  sprint dedicado — no a este ciclo.
- **EDGE-06** — Ciclado del dyno con SSE/WS activos → stream cortado; el
  frontend ya cierra limpio (`onDone` sin `done`; `onclose` del WS).
  Aceptado por NFR-05.
- **EDGE-07** — Imagen falla el boot por layers/tamaño (P6) → adelgazar la
  imagen multi-stage antes de considerar cualquier cambio de dyno.
- **EDGE-08** — Replit cae ANTES del verify verde → se acepta el downtime,
  no se reanima Replit, se acelera el E2E. Es exactamente el riesgo que
  motiva la urgencia.
- **EDGE-09** — Key inválida en config vars → el backend bootea igual
  (verificado: keys opcionales al boot; CV responde 503 con detalle claro,
  STT devuelve vacío con warning). El E2E lo delataría vía AC-03/AC-05.

## Manejo de Errores

- H12 en CV generate → usuario: error del `ApiError` con status; logs: H12.
  Acción: NFR-03/EDGE-05.
- H15/H28 en WS de audio → usuario: la conexión de audio se cierra; logs:
  H15/H28. Acción: EDGE-02.
- R14/R15 de memoria → usuario: latencia o corte momentáneo tras restart;
  logs: R14/R15. Acción: trigger de NFR-04.
- Fallo de boot (bind a `$PORT`, P6) → release ok pero dyno en crash-loop;
  `heroku logs --tail` es la fuente de diagnóstico. Acción: revisar sección
  `run` de REQ-05.
- `/` en 404 con `/health` en 200 → layout de imagen roto. Acción:
  EDGE-03/REQ-04.

## Archivos afectados (estimado)

- `heroku.yml` — nuevo, raíz.
- `Dockerfile` — nuevo, raíz (deploy).
- `backend/Dockerfile` — SOLO el comentario cruzado de la guardia de drift
  (REQ-02); ningún cambio funcional.
- `README.md`, `CLAUDE.md`, `HANDOFF.md` — solo en cutover post-verify
  (REQ-09).
- `.replit`, `replit.nix` — eliminados solo post-verify (REQ-08/09).
- **Cero archivos** bajo `backend/app/**` y `frontend/src/**`.

## Definition of Done

- [ ] **AC-01** — `GET /health` → 200 `{"status":"ok"}` en el dominio Heroku.
- [ ] **AC-02** — `/` sirve el frontend y React monta (descarta EDGE-03).
- [ ] **AC-03** — Flujo CV completo: job posting real → 200 con `ats_score`
  numérico, `cv_html` no vacío, preview visible y Print to PDF abriendo su
  ventana.
- [ ] **AC-04** — SSE del copilot: pregunta de entrevista → frames `meta` +
  `chunk` progresivos + `done` visibles en la UI.
- [ ] **AC-05** — WS audio (Chrome desktop): grabación corta (~10 s) →
  transcript con prefijo `[Transcribed]` en el textarea.
- [ ] **AC-06** — Grabación > 90 s: llega el transcript (hipótesis NFR-02
  confirmada) **o** queda registrada la limitación EDGE-02 con issue a 1B.
  Binario de dos ramas: una de las dos queda documentada. (Aprobado así por
  CTO.)
- [ ] **AC-07** — El bundle JS servido en producción no contiene
  `localhost:8000` (descarta EDGE-04).
- [ ] **AC-08** — Logs de la sesión E2E sin H12/H15/R14 en los flujos de
  AC-03/04/05.
- [ ] **AC-09** — Config vars presentes en Heroku; el diff del repo no
  contiene ningún secreto (grep de llaves).
- [ ] **AC-10** — Rama `chore/heroku-migration` pusheada; el diff no toca
  `backend/app/**` ni `frontend/src/**` (única excepción: comentario de
  REQ-02 en `backend/Dockerfile`, que no está bajo `backend/app/`).
- [ ] **AC-11** — Cutover ejecutado post-verify: URLs actualizadas,
  `.replit`/`replit.nix` retirados, Replit sin tocar hasta ese momento.

## Verificación E2E

Definición base (HANDOFF §3): `/health` 200 + CV generado con ATS score +
SSE del copilot + audio WS, todo en el dominio nuevo. Mapeo: **AC-01 +
AC-03 + AC-04 + AC-05** constituyen ese E2E mínimo del cutover; **AC-02,
AC-06, AC-07 y AC-08** son las verificaciones adicionales que la auditoría
de esta sesión agrega por riesgos específicos de la plataforma (layout de
imagen, idle del router sobre WS, fallback silencioso del bundle, salud de
memoria).

Protocolo: ejecutar en orden AC-01 → AC-02 → AC-03 → AC-04 → AC-05 → AC-06
→ AC-07, con `heroku logs --tail` corriendo en paralelo durante toda la
sesión (alimenta AC-08). Para la medición de NFR-03, una de las corridas de
AC-03 usa un input de bajo fit deliberado que fuerce el camino del rewrite.
Navegador: Chrome desktop (restricción Safari/mobile conocida, HANDOFF §2 —
sin cambio). Evidencia mínima por AC: respuesta HTTP o captura de UI +
extracto de log. Solo con los once AC en verde (o AC-06 en su rama
documentada) el ciclo pasa a verify y de ahí al cutover de REQ-09.

---

*Aprobado: 15 Jul 2026 · Cambios de revisión CTO incorporados: guardia de
drift en REQ-02, EDGE-05 corregido contra el repo (rewrite automático por
umbral, sin flag), tabla P3 limpiada.*
