# Plan: migracion-sdk-gemini

Spec de referencia: `docs/specs/migracion-sdk-gemini.md` (v1.1)
Rama de trabajo: `fix/gemini-sdk-migration` — **creada desde `chore/heroku-migration`**, NO desde main
Ejecutor: Sonnet (Claude Code CLI) · Máquina sin Docker · El deploy de prueba va a Heroku desde esta rama

---

## Contexto de dominio

Claude Code no ve Notion ni las sesiones de Claude App. Todo lo necesario está aquí. Hechos verificados el 18 Jul 2026; NO los re-derives.

### Estado y causa raíz
- Producción (app Heroku `career-ai`, config v12) responde `404 This model models/gemini-2.5-flash-lite is no longer available to new users` con billing activo y credencial válida. Google cierra los modelos 2.5 a cuentas nuevas de AI Studio; además el SDK pineado `google-generativeai==0.8.3` está oficialmente deprecado (monta la superficie `google-ai-generativelanguage==0.6.10`, congelada de 2024).
- Por eso el fix tiene DOS partes inseparables: SDK nuevo (`google-genai==2.12.1`, estable actual verificado en PyPI) + modelo destino resuelto empíricamente (`TARGET_MODEL`).

### Interfaz actual de `llm_client.py` (verificada contra el repo — PRESERVAR INTACTA)
- Funciones públicas: `extract_job_title(job_posting) -> str` · `extract_keywords(job_posting) -> list[str]` · `rewrite_bullets(bullets, missing)` · `generate_suggestion(text, intent, language)` (async generator que alimenta el SSE).
- Excepciones tipadas del módulo: `LLMConfigError` (key ausente), `LLMResponseError` (respuesta imparseable), `LLMRateLimitError` (cuota). Los endpoints las traducen a HTTP — NO cambies nombres ni semántica.
- Patrón actual: SDK síncrono + ejecución en executor para no bloquear el event loop (el streaming usa `model.generate_content(..., stream=True)` dentro del executor, línea ~377). **Conserva este patrón**: usa el cliente síncrono del SDK nuevo con el mismo envoltorio async existente. No migres a `client.aio` — minimiza la superficie del cambio.
- `_strip_code_fences` (línea ~173) ya tolera respuestas envueltas en fences markdown — consérvalo tal cual; cubre el riesgo de formato de los modelos 3.x.
- `_MODEL_ALIASES = {}` existe en el módulo — es el gancho a poblar.
- Consumidores: `cv_engine.py` (extract_keywords, rewrite_bullets, extract_job_title) e `interview.py` (generate_suggestion + import de excepciones). Ninguno se toca.

### Mapeo SDK viejo → nuevo (por sitio de llamada)
- `genai.configure(api_key=...)` + `genai.GenerativeModel(name)` → `client = genai.Client(api_key=...)` (import: `from google import genai`); el cliente se crea lazy en el equivalente de `_get_model()` y se cachea a nivel de módulo.
- `model.generate_content(prompt)` → `client.models.generate_content(model=RESOLVED_MODEL, contents=prompt)`; la respuesta expone `.text` igual.
- `model.generate_content(prompt, stream=True)` → `client.models.generate_content_stream(model=..., contents=...)` — iterador síncrono de chunks con `.text`; se consume dentro del executor como hoy.
- Excepciones: el SDK nuevo usa `from google.genai import errors` (clases tipo `APIError`/`ClientError` con código de status). **Al implementar, inspecciona `google.genai.errors` del paquete instalado** (`python -c "from google.genai import errors; print([n for n in dir(errors) if not n.startswith('_')])"`) y mapea: status 429 → `LLMRateLimitError`; el resto conserva la semántica actual (propagar/`LLMResponseError` según el sitio, igual que hoy con `ResourceExhausted`). No confíes en memoria para los nombres de clase.
- Resolución de modelo: función interna que aplica `_MODEL_ALIASES` sobre `settings.GEMINI_MODEL` y emite `logger.warning` cuando resuelve un alias; loguea el modelo activo una vez al crear el cliente.

### Reglas de system design aplicables
- Regla 6 (resiliencia): timeouts SIGUEN FUERA de alcance — deuda registrada, no la "aproveches". Cero retries nuevos.
- Regla 10 (sistemas adyacentes): la preservación de interfaz ES la protección de CV Engine y SSE. Si en algún punto crees necesario tocar `cv_engine.py`, `interview.py`, prompts o parsing → DETENTE y reporta: está fuera del spec.
- Anti-over-engineering: la solución más simple que cumple el DoD gana.

### Restricciones duras del ciclo
- Diff permitido: EXACTAMENTE `backend/requirements.txt`, `backend/app/services/llm_client.py`, `backend/app/config.py`, `.env.example`. Nada más.
- Scripts de smoke: efímeros en `/tmp/`, JAMÁS commiteados.
- Secretos: jamás en commits, outputs ni reportes (la key solo se lee del `.env`).
- Replit y los archivos del ciclo #1 (Dockerfile, heroku.yml, docs/): intocados.

---

## Tasks

### Task 0: Gate de entorno (sin commit)
**Archivo(s):** ninguno
**Qué hacer:**
- `git fetch origin && git checkout chore/heroku-migration && git pull` → crear `fix/gemini-sdk-migration` desde ahí. Confirmar con `git log --oneline -1` que el HEAD es `e38d18b` o descendiente.
- Verificar `.env` local con `GEMINI_API_KEY` no-placeholder (grep del nombre; NO imprimir el valor) — debe ser la key nueva con billing.
- `heroku auth:whoami` → 0 con email.
- `python3 -m venv /tmp/genai-venv && /tmp/genai-venv/bin/pip install google-genai==2.12.1` → instala sin error.
**Verificación:** los 4 checks pasan; si cualquiera falla, detente y reporta.
**Commit message:** N/A (gate)

### Task 1: Descubrimiento de modelo — AC-1.5-00 (sin commit)
**Archivo(s):** ninguno (script efímero en /tmp/)
**Qué hacer:**
- Script en `/tmp/discover.py` con el venv: crear `genai.Client` con la key del `.env`; iterar `client.models.list()`; imprimir SOLO los ids que soporten generación de contenido y contengan `flash` (sin tokens ni metadata sensible).
- Resolver `TARGET_MODEL` por orden de preferencia: `gemini-2.5-flash-lite` → `gemini-3.1-flash-lite` → `gemini-3-flash` (o el id exacto más cercano listado, p. ej. variante `-preview` si es lo único) → el Flash-Lite/Flash más económico disponible. Los modelos Pro NO son candidatos.
- Con el `TARGET_MODEL` elegido: 1 llamada `generate_content` mínima ("responde OK") → debe regresar texto sin excepción.
- **Si ningún candidato está disponible o todos fallan: DETENTE y reporta el listado completo — decisión humana, no improvises.**
**Verificación:** reporte con el listado de ids y el `TARGET_MODEL` literal + confirmación del 200. Binario: hay TARGET con generación exitosa, o hay stop reportado.
**Commit message:** N/A

### Task 2: Dependencia y configuración
**Archivo(s):** `backend/requirements.txt`, `backend/app/config.py`, `.env.example`
**Qué hacer:**
- requirements: eliminar `google-generativeai==0.8.3`; agregar `google-genai==2.12.1` (mismo bloque comentado "LLM client").
- config.py: default de `GEMINI_MODEL` → el `TARGET_MODEL` de Task 1 (string literal).
- .env.example: actualizar el valor de ejemplo de `GEMINI_MODEL` al mismo id.
**Verificación:** `grep -n "google-genai==2.12.1" backend/requirements.txt` y `grep -rn "<TARGET_MODEL>" backend/app/config.py .env.example` devuelven las líneas; `grep google-generativeai backend/requirements.txt` vacío.
**Commit message:** `fix(llm): swap deprecated google-generativeai for google-genai and update default model`

### Task 3: Reescritura del cliente
**Archivo(s):** `backend/app/services/llm_client.py`
**Qué hacer:**
- Aplicar el mapeo por sitio de llamada del Contexto de dominio: imports, cliente lazy cacheado, `generate_content`, streaming, y el mapeo de excepciones inspeccionado del paquete instalado (429 → `LLMRateLimitError`; resto = semántica actual).
- Poblar `_MODEL_ALIASES` con `gemini-1.5-flash`, `gemini-2.0-flash`, `gemini-2.5-flash` → TARGET_MODEL; agregar `gemini-2.5-flash-lite` → TARGET_MODEL solo si TARGET difiere de ese id.
- Resolución de alias con `logger.warning("GEMINI_MODEL '%s' resuelto por alias a '%s'", ...)`; log del modelo activo al crear el cliente.
- Interfaz pública, docstrings de contrato, `_strip_code_fences`, `_first_nonempty_line` y el patrón executor: intactos.
**Verificación:** `python -c "import ast; ast.parse(open('backend/app/services/llm_client.py').read())"` OK; `grep` confirma: cero referencias a `google.generativeai` y a `google.api_core`; las 4 funciones públicas conservan nombre y firma; `_MODEL_ALIASES` con las entradas.
**Commit message:** `fix(llm): migrate llm_client to google-genai SDK with model aliases`

### Task 4: Smoke local completo — AC-1.5-01 y AC-1.5-04 (sin commit)
**Archivo(s):** ninguno (script efímero en /tmp/)
**Qué hacer:**
- Instalar los requirements del backend en el venv (o `pip install google-genai==2.12.1 pydantic pydantic-settings fastapi` mínimos para importar el módulo) y, desde `/tmp/smoke.py` con `backend/` en `sys.path` y el `.env` cargado: ejecutar los 4 caminos — `extract_job_title` y `extract_keywords` con un posting corto real, `rewrite_bullets` con 1 bullet y 1 keyword, y `generate_suggestion` consumiendo el generador completo (contar chunks > 0).
- AC-1.5-04: exportar `GEMINI_MODEL=gemini-2.5-flash` solo en el proceso del script, repetir 1 llamada y confirmar el warning de alias en el log; el `.env` no se modifica.
**Verificación:** los 4 caminos regresan datos no vacíos sin excepción; el warning de alias aparece; nada impreso contiene la key. Binario por camino.
**Commit message:** N/A

### Task 5: Config var y deploy
**Archivo(s):** ninguno (plataforma)
**Qué hacer:**
- Si `TARGET_MODEL` ≠ valor actual: `heroku config:set GEMINI_MODEL=<TARGET_MODEL> --app career-ai`.
- `git push -u origin fix/gemini-sdk-migration` y `git push heroku fix/gemini-sdk-migration:main` → build remoto instala el pin nuevo.
- Si el build falla: error literal, fixes SOLO dentro de los 4 archivos permitidos, máx. 3 iteraciones, luego stop y reporte.
**Verificación:** build exitoso; `heroku ps` → `web.1: up`; `heroku config:get GEMINI_MODEL` = TARGET_MODEL (imprimir este valor sí está permitido — no es secreto).
**Commit message:** N/A (fixes: `fix(llm): <detalle>`)

### Task 6: Re-test en producción — AC-1.5-02/03/06
**Archivo(s):** ninguno
**Qué hacer (contra `https://career-ai-95daf7c9a813.herokuapp.com`):**
- `curl /health` → 200 `{"status":"ok"}`.
- POST `/api/cv/generate` con payload mínimo real (job posting corto + perfil de 1 experiencia) → 200 con `ats_score` numérico y `cv_html` no vacío (AC-1.5-02) — el mismo flujo que hoy devuelve 500.
- `curl -N` a `/api/interview/text` con una pregunta de entrevista → frames `meta`, `chunk` (≥1) y `done` (AC-1.5-03).
- 30 líneas de `heroku logs` posteriores: sin tracebacks nuevos ni H12/H15/R14; el warning de alias no cuenta como error (AC-1.5-06).
**Verificación:** outputs literales de los 4 checks en el reporte.
**Commit message:** N/A

### Task 7: Reporte final
**Archivo(s):** ninguno
**Qué hacer:**
- Push final confirmado a origin. Reportar: `TARGET_MODEL` literal y el listado de Task 1, rama, SHA del último commit pusheado, outputs de Task 6, desviaciones etiquetadas.
- Declarar pendientes fuera de tu alcance: E2E de navegador del ciclo #1 (AC-03/04/05/06 + AC-08, incluida grabación >90s e input de bajo fit), verify de la unión de ambas ramas, merges en cadena, cutover AC-11. **No declares ningún ciclo completado.**
**Verificación:** reporte con los 6 elementos; rama visible en GitHub.
**Commit message:** N/A

---

## Orden de ejecución
1. Task 0 (gate — bloquea todo)
2. Task 1 (AC-1.5-00; puede detener el ciclo)
3. Task 2 → 4. Task 3 (dependen del TARGET de Task 1)
5. Task 4 (depende de 2-3)
6. Task 5 (depende de 4 en verde)
7. Task 6 (depende de 5)
8. Task 7 (cierre)

## Tests requeridos
- [ ] Task 1 y Task 4 — LOCAL (MacBook, venv en /tmp; sin Docker). Gates bloqueantes antes de cualquier deploy.
- [ ] Task 6 completa — contra producción vía curl. Sin Docker.
- [ ] E2E de navegador — HUMANO, fuera de este plan, declarado en Task 7.

## Riesgos
- Ningún modelo del orden de preferencia disponible → stop de Task 1, decisión humana (edge del spec).
- Nombres de excepciones del SDK nuevo distintos a lo esperado → mitigación: inspección del paquete instalado en vez de memoria (Contexto de dominio).
- Formato de respuesta de modelos 3.x → mitigación: `_strip_code_fences` existente + smoke de los 4 caminos antes del deploy.
- Streaming con shape de chunks distinto → mitigación: AC-1.5-01 consume el generador completo en local antes de deployar.
- Costo por token mayor en línea 3.x (~3× la 2.5-lite) → contenido por tope de billing y quota caps ya activos; volumen actual = centavos.
- Scope creep hacia cv_engine/prompts → prohibición explícita con stop-and-report.

---

## Prompt para pasar a Sonnet

```
Lee HANDOFF.md primero.

Crea la rama fix/gemini-sdk-migration DESDE chore/heroku-migration (no desde
main) ANTES de tocar cualquier archivo.

Lee docs/plans/migracion-sdk-gemini-plan.md y ejecútalo task por task, en
orden, sin desviarte. El spec (v1.1) está en docs/specs/migracion-sdk-gemini.md
por si necesitas el porqué de una decisión — pero el plan manda.

Reglas:
- Task 0 es gate; Task 1 puede DETENER el ciclo (si ningún modelo candidato
  está disponible, reportas y paras — no improvisas).
- Un commit por task (donde aplique). OBLIGATORIO: push de la rama a origin
  al terminar y preferible tras cada task — el CTO verifica contra el
  remoto, no contra reportes. Esta regla ya falló dos veces sin ella.
- El diff solo puede tocar: backend/requirements.txt,
  backend/app/services/llm_client.py, backend/app/config.py, .env.example.
- NO corras Docker localmente. El build es el push a Heroku (Task 5).
- Nunca imprimas la API key en ningún output.
- Ambigüedad → pregunta antes de asumir. HANDOFF contradice el plan →
  reporta, no resuelvas solo.
- Al terminar: reporta TARGET_MODEL, rama, SHA pusheado y outputs literales
  de Task 6. Declara los pendientes de Task 7 — NO declares el ciclo
  completado.
```

---
*Generado: 18 Jul 2026 · Basado en spec v1.1 · Pendiente de firma humana (spec v1.1 + plan juntos) antes de pasar a Sonnet.*
