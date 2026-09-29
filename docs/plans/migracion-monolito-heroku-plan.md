# Plan: migracion-monolito-heroku

Spec de referencia: `docs/specs/migracion-monolito-heroku.md` (APROBADO 15 Jul 2026)
Rama de trabajo: `chore/heroku-migration`
Ejecutor: Sonnet (Claude Code CLI) · Máquina sin Docker — el build ocurre en Heroku (hecho P4)

---

## Contexto de dominio

Claude Code no ve Notion ni la sesión de Claude App. Todo lo que necesitas
está aquí. Estos hechos fueron verificados el 15 Jul 2026 contra la
documentación oficial de Heroku y contra el repo real; NO los re-derives ni
los contradigas — si algo en el repo parece contradecirlos, reporta y detente.

### Hechos de plataforma y repo (P1–P9)

| # | Hecho |
|---|---|
| P1 | Router de Heroku: 30 s de ventana inicial para el primer byte de respuesta (H12 si se excede); después, cada byte en cualquier dirección resetea una ventana rodante de 55 s; sin datos en 55 s la conexión se corta (H15/H28). El dyno NO se entera del corte y sigue procesando. |
| P2 | La ventana rodante de 55 s aplica también a WebSockets; los pings de protocolo cuentan como tráfico. |
| P3 | En heroku.yml, el contexto de build de Docker es SIEMPRE el directorio que contiene el Dockerfile (no configurable). `build.config` define variables de build-time que deben tener su `ARG` correspondiente en el Dockerfile; NO crean config vars de runtime, y las config vars de runtime NO existen durante el build. Sin sección `run`, Heroku usa el CMD del Dockerfile. |
| P4 | Con el stack de la app en `container` y un heroku.yml en la raíz, `git push heroku <rama>:main` construye la imagen EN Heroku. No se necesita Docker local. |
| P5 | Basic dyno: $7/mes máximo, 512 MB RAM, no duerme, máximo 1 dyno por process type. |
| P6 | El proceso web debe bindear a `$PORT` dentro de 60 s del boot. En restarts: SIGTERM → 30 s → SIGKILL. R15 si la memoria alcanza 2× la cuota (1 GB en basic). Imagen OCI máx. 5 GB; > 40 layers puede fallar el boot. |
| P7 | uvicorn 0.32.1 (pineado en requirements.txt) manda pings WS cada 20 s por default — por debajo de la ventana de P2. No cambies esa versión ni configures `--ws-ping-interval`. |
| P8 | `backend/app/main.py` resuelve el frontend como `Path(__file__).parents[2] / "frontend" / "dist"` y solo monta StaticFiles si el directorio existe. El layout de la imagen DEBE replicar la relación `<raíz>/backend/app/` ↔ `<raíz>/frontend/dist`. NO toques main.py. |
| P9 | El frontend lee `VITE_API_URL` en BUILD time (Vite) con fallback silencioso a `http://localhost:8000` en `client.ts` e `InterviewCopilot.tsx`. Un build sin la variable produce una app rota solo detectable en runtime. |

### Reglas de system design aplicables (del RAG Backend System Design)

- **Regla 3 (protocolos):** el copilot usa SSE y el audio usa WS — correcto
  para tiempo real; esta migración NO cambia protocolos, solo debe garantizar
  que sobreviven al router (P1/P2). No introduzcas polling ni cambies el
  transporte.
- **Regla 6 (resiliencia en llamadas externas):** el código actual NO tiene
  timeouts en llamadas a Gemini/Deepgram (verificado por grep). Es deuda
  registrada en el spec — NO la arregles en este ciclo; agregarlos sería
  cambio de código de app, fuera de alcance.
- **Regla 7 (CAP):** se eligió disponibilidad; app stateless, `/tmp` efímero,
  reinicios aceptados. No agregues persistencia.
- **Regla 8 (escalera de escalado):** un solo Basic dyno. NO configures
  workers, ni autoscaling, ni cambies el tipo de dyno. El trigger para
  subir a Standard-1X es R14 recurrente en uso normal — decisión del CTO,
  no tuya.

### Restricciones duras del ciclo

- CERO cambios bajo `backend/app/**` y `frontend/src/**`.
- Única edición permitida a un archivo existente de build:
  `backend/Dockerfile` recibe SOLO un comentario (Task 2).
- Replit intocable: no edites `.replit` ni `replit.nix`, no toques nada en
  replit.com (REQ-08 del spec). Su eliminación es post-verify y NO es parte
  de este plan.
- El cutover de docs (README/CLAUDE.md/HANDOFF) es post-verify y NO es
  parte de este plan.
- Secretos: JAMÁS en commits, JAMÁS en tu reporte en texto plano. Los
  valores reales viven en el `.env` local (gitignored) y en Heroku Config
  Vars.

---

## Tasks

### Task 0: Gate de entorno (sin commit)
**Archivo(s):** ninguno
**Qué hacer:**
- Verificar CLI de Heroku instalada y sesión activa: `heroku auth:whoami`
  debe salir con código 0 e imprimir el email de la cuenta.
- Verificar working tree limpio: `git status --porcelain` vacío sobre `main`
  actualizado (`git pull origin main`).
- Verificar que existe `.env` local con `GEMINI_API_KEY`, `DEEPGRAM_API_KEY`
  y `GEMINI_MODEL` con valores no-placeholder (grep de los nombres; NO
  imprimas los valores).
- Verificar espacio libre en disco: `df -h /` debe mostrar ≥ 2 GB disponibles
  en el filesystem raíz. Lección registrada tras este ciclo: sin este check,
  un build multi-stage o un `git push` puede fallar a mitad de camino por
  falta de espacio, sin aviso previo y con estado intermedio difícil de
  diagnosticar.
**Verificación:** los cuatro comandos pasan. Si CUALQUIERA falla → detente y
reporta al humano; no continúes con el plan.
**Commit message:** N/A (gate)

### Task 1: Dockerfile de deploy en la raíz
**Archivo(s):** `Dockerfile` (nuevo, raíz del repo)
**Qué hacer:**
- Multi-stage. Etapa 1 (`AS frontend-build`): base `node:20-alpine`,
  `WORKDIR /build`, copiar `frontend/package*.json`, `npm ci` (o
  `npm install` si no hay lockfile), copiar el resto de `frontend/`,
  declarar `ARG VITE_API_URL` y exportarlo como `ENV VITE_API_URL=$VITE_API_URL`
  antes de `npm run build`.
- Etapa 2 (final): base `python:3.11-slim`. Instalar por apt EXACTAMENTE las
  libs nativas listadas en `backend/Dockerfile` (libpango-1.0-0,
  libpangoft2-1.0-0, libcairo2, libgdk-pixbuf-2.0-0, libffi-dev,
  shared-mime-info, fonts-dejavu) con `--no-install-recommends` y limpieza
  de listas apt.
- Layout que satisface P8: `WORKDIR /srv/backend`; copiar
  `backend/requirements.txt` e instalar con pip (`--no-cache-dir`); copiar
  `backend/` a `/srv/backend/`; copiar desde la etapa 1 el build a
  `/srv/frontend/dist`. Resultado: `/srv/backend/app/main.py` →
  `parents[2]` = `/srv` → `/srv/frontend/dist` existe. 
- SIN `CMD`: el comando de arranque vive en `heroku.yml` (REQ-05). Dejar un
  comentario que lo diga.
- Comentario de guardia de drift al inicio del archivo: la lista de libs
  nativas de WeasyPrint está duplicada con `backend/Dockerfile`; cualquier
  cambio debe replicarse en ambos.
**Verificación:** el archivo existe y `grep` confirma: `ARG VITE_API_URL`,
las 7 libs nativas, `frontend/dist`, ausencia de `CMD`, presencia del
comentario de drift. (El build real se verifica en Task 5 — no hay Docker
local.)
**Commit message:** `chore(deploy): add multi-stage Heroku Dockerfile`

### Task 2: Comentario de drift en backend/Dockerfile
**Archivo(s):** `backend/Dockerfile`
**Qué hacer:**
- Agregar, junto al bloque apt existente, un comentario que remita al
  `Dockerfile` de la raíz: la lista de libs nativas está duplicada allí para
  el deploy en Heroku y cualquier cambio debe replicarse en ambos archivos.
- NINGÚN otro cambio en el archivo (ni CMD, ni puertos, ni layers).
**Verificación:** `git diff backend/Dockerfile` muestra únicamente líneas de
comentario añadidas (todas empiezan con `#`).
**Commit message:** `docs(deploy): cross-reference native libs drift guard in backend Dockerfile`

### Task 3: Crear la app Heroku y registrar el dominio (sin commit)
**Archivo(s):** ninguno (operación de plataforma)
**Qué hacer:**
- `heroku create career-ai --stack container --region us`. Si el nombre está
  ocupado (EDGE-01), usar `career-ai-adw`; si también, `careerai-adw`.
- `heroku git:remote -a <nombre-final>` para fijar el remote.
- Registrar el dominio web exacto que imprime el create (formato
  `https://<nombre>-<hash>.herokuapp.com`). Ese dominio es la fuente de
  verdad para Task 4 y Task 5 — apúntalo literal en tu reporte.
- Confirmar `heroku apps:info` muestra `Stack: container` y el Web URL.
**Verificación:** `heroku apps:info` con stack container y dyno formation
vacía (aún sin release). Dominio registrado en el reporte.
**Commit message:** N/A (plataforma)

### Task 4: heroku.yml con el dominio real
**Archivo(s):** `heroku.yml` (nuevo, raíz del repo)
**Qué hacer:**
- Sección `build.docker.web: Dockerfile` (el de la raíz — con esto el
  contexto de build es la raíz del repo, P3, y el Dockerfile ve `frontend/`
  y `backend/`).
- Sección `build.config` con `VITE_API_URL: <dominio registrado en Task 3>`
  (sin slash final — `client.ts` lo recorta, pero mantén el valor limpio).
  Este valor NO es secreto: es el dominio público. P3: debe corresponder al
  `ARG` de la Task 1.
- Sección `run.web` con el arranque de uvicorn: desde el directorio del
  backend dentro de la imagen (`/srv/backend`), `uvicorn app.main:app
  --host 0.0.0.0 --port $PORT`. Nota: `run` de heroku.yml corre con shell,
  `$PORT` se expande; el working dir por defecto es el WORKDIR de la imagen
  (`/srv/backend` por Task 1), así que el módulo `app.main` resuelve.
**Verificación:** el archivo existe; `grep` confirma `web: Dockerfile`,
`VITE_API_URL: https://` (dominio real, no localhost, no placeholder) y
`--port $PORT`.
**Commit message:** `chore(deploy): add heroku.yml manifest for container stack`

### Task 5: Config vars de runtime (sin commit)
**Archivo(s):** ninguno (operación de plataforma)
**Qué hacer:**
- Leer los valores reales desde el `.env` local (verificado en Task 0) y
  fijarlos: `heroku config:set GEMINI_API_KEY=... GEMINI_MODEL=...
  DEEPGRAM_API_KEY=... CV_OUTPUT_DIR=/tmp/cvs
  CORS_ORIGINS="<dominio de Task 3>,http://localhost:5173"`.
- Ejecuta el comando de forma que los valores NO queden en tu reporte; en el
  reporte lista solo los NOMBRES de las 5 vars.
**Verificación:** `heroku config` lista exactamente esas 5 keys (los valores
salen enmascarados o se omiten del reporte).
**Commit message:** N/A (plataforma)

### Task 6: Push y build remoto
**Archivo(s):** ninguno (deploy)
**Qué hacer:**
- Push de la rama a GitHub primero: `git push -u origin chore/heroku-migration`.
- Deploy: `git push heroku chore/heroku-migration:main`. El build multi-stage
  corre en Heroku (P4); observa el output completo.
- Si el build falla: captura el error literal, NO improvises fixes fuera del
  alcance de las Tasks 1/4; corrige solo dentro de esos dos archivos,
  commitea, push a AMBOS remotos y reintenta. Máximo 3 iteraciones; a la
  tercera fallida, detente y reporta.
- Tras release: `heroku ps` debe mostrar `web.1: up`.
**Verificación:** build exitoso + `heroku ps` con web.1 up. Si el dyno
crashea al boot, `heroku logs --tail` y revisar contra P6/P8 (bind a $PORT,
layout de dist) antes de reintentar.
**Commit message:** N/A (deploy; los commits de fixes usan
`fix(deploy): <detalle>`)

### Task 7: Smoke E2E automatizable
**Archivo(s):** ninguno
**Qué hacer (contra el dominio de Task 3):**
- AC-01: `curl -s -o /dev/null -w "%{http_code}" <dominio>/health` → `200`;
  `curl -s <dominio>/health` → `{"status":"ok"}`.
- AC-02 (parcial): `curl -s <dominio>/` contiene el marcador del index de
  Vite (`<div id="root">` o equivalente del `frontend/index.html`).
- AC-07: extraer del HTML la ruta del bundle JS (`/assets/*.js`),
  descargarlo con curl y `grep -c "localhost:8000"` → `0`.
- Capturar 30 líneas de `heroku logs` posteriores a los curls y verificar
  ausencia de H12/H15/R14 (aporte parcial a AC-08).
**Verificación:** los cuatro checks en verde, con outputs literales en el
reporte.
**Commit message:** N/A

### Task 8: Reporte final y cierre de la fase Sonnet
**Archivo(s):** ninguno
**Qué hacer:**
- Push final de la rama a origin (obligatorio aunque no haya commits nuevos
  desde Task 6: confirma que el remoto está al día).
- Reportar: nombre exacto de la rama, SHA del último commit pusheado,
  dominio de producción, nombres (no valores) de las config vars, output
  literal de los checks de Task 7, y cualquier desviación etiquetada.
- Declarar EXPLÍCITAMENTE lo que queda fuera de tu alcance y pendiente para
  humano + verify: AC-03/04/05/06 (E2E de navegador en Chrome desktop,
  incluida la grabación > 90 s y el input de bajo fit para NFR-03), AC-11
  (cutover de docs y retiro de `.replit`/`replit.nix`), y el merge. NO
  declares el ciclo completado — completaste la fase de ejecución.
**Verificación:** reporte emitido con los 6 elementos; rama visible en
GitHub con los commits de Tasks 1, 2 y 4.
**Commit message:** N/A

---

## Orden de ejecución

1. Task 0 (gate — bloquea todo)
2. Task 1 (sin dependencias tras el gate)
3. Task 2 (independiente de Task 1; misma rama)
4. Task 3 (plataforma; necesaria antes de Task 4 por el dominio)
5. Task 4 (depende de Task 1 y Task 3)
6. Task 5 (depende de Task 3; puede correr antes o después de Task 4)
7. Task 6 (depende de Tasks 1–5)
8. Task 7 (depende de Task 6)
9. Task 8 (cierre)

## Tests requeridos

- [ ] Task 0: `heroku auth:whoami` — LOCAL (MacBook). Gate bloqueante.
- [ ] Task 0: `df -h /` con ≥ 2 GB disponibles — LOCAL (MacBook). Gate
      bloqueante.
- [ ] Task 7 completa (curls AC-01/02/07 + logs) — LOCAL contra el dominio
      de producción. No requiere Docker ni stack local.
- [ ] NO correr docker compose ni builds de imagen localmente — esta máquina
      no tiene Docker; el build ES el push de Task 6.
- [ ] E2E de navegador (AC-03/04/05/06) — HUMANO en Chrome desktop, fuera de
      este plan; queda declarado como pendiente en Task 8.

## Riesgos

- Build remoto falla por contexto/paths (P3/P8) → mitigación: Task 1 fija el
  layout exacto y Task 6 limita a 3 iteraciones de fix antes de escalar.
- Bundle con fallback localhost (P9/EDGE-04) → mitigación: `ARG`+`ENV` en
  Task 1, dominio real en Task 4, check AC-07 en Task 7.
- Dyno no bindea $PORT en 60 s (P6) → mitigación: `run.web` explícito con
  `$PORT` en Task 4; diagnóstico por logs en Task 6.
- WS muere en grabaciones largas pese a pings (P2/P7) → fuera del alcance de
  Sonnet; lo resuelve el binario de dos ramas de AC-06 en el E2E humano.
- Secreto filtrado a commit o reporte → mitigación: Tasks 0/5 prohíben
  imprimir valores; AC-09 lo audita en verify.
- Replit se cae a mitad del plan (EDGE-08) → no cambia nada: continuar, no
  reanimar Replit, acelerar.

---

## Prompt para pasar a Sonnet

```
Lee HANDOFF.md primero.

Crea la rama chore/heroku-migration ANTES de tocar cualquier archivo.

Lee docs/plans/migracion-monolito-heroku-plan.md y ejecútalo task por task,
en orden, sin desviarte. El spec de referencia está en
docs/specs/migracion-monolito-heroku.md por si necesitas contexto de una
decisión — pero el plan manda.

Reglas:
- Task 0 es un gate: si heroku auth:whoami falla, o si `df -h /` muestra
  menos de 2 GB disponibles, detente y reporta.
- Un commit por task completada (donde aplique), en la rama
  chore/heroku-migration.
- OBLIGATORIO al terminar (y preferible tras cada task): git push de la
  rama a origin. Nada queda solo en el working tree — el CTO verifica
  contra el remoto, no contra reportes. Esta regla existe porque ya falló
  dos veces sin ella.
- NO corras docker compose ni builds de imagen localmente (esta máquina no
  puede correr Docker). El build de la imagen ES el push a Heroku (Task 6).
- Nunca imprimas valores de secretos en commits ni en tu reporte.
- Si encuentras ambigüedad → pregunta antes de asumir.
- Si algo en HANDOFF.md contradice el plan → reportar, no resolver solo.
- Al terminar: reporta rama exacta, SHA del último commit pusheado, dominio
  de producción, y el output literal de los checks de Task 7. Declara los
  pendientes de la Task 8 — NO declares el ciclo completado.
```

---

*Generado: 15 Jul 2026 · Ciclo SDD #1 · Pendiente de revisión humana antes
de pasar a Sonnet.*
