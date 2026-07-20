# Spec: migracion-sdk-gemini

> Ciclo SDD #1.5 (mini-ciclo) · Desbloqueante del E2E del Ciclo #1
> Versión: **v1.1** (enmienda post-aprobación, ver changelog al pie)
> Estado: v1.0 APROBADA por operador (18 Jul 2026, sin /cto-review — decisión registrada). Enmienda v1.1 presentada junto con el plan para firma conjunta.
> Rama: `fix/gemini-sdk-migration` **desde `chore/heroku-migration`** (apilada — necesita Dockerfile/heroku.yml para deployar el re-test).

## Resumen General

Migrar el cliente LLM del SDK legacy `google-generativeai==0.8.3` (deprecado, superficie de API congelada de 2024) al SDK oficial `google-genai==2.12.1`, y apuntar producción a un modelo **que la cuenta realmente pueda usar**. Causa raíz cerrada por evidencia empírica (log v12): `404 This model models/gemini-2.5-flash-lite is no longer available to new users` — Google cierra los modelos 2.5 a cuentas nuevas de AI Studio. El SDK legacy sigue siendo bloqueante por derecho propio (deprecado + churn continuo, próximo cutover 3.x anunciado para oct-2026), pero el modelo destino NO puede fijarse a ciegas: se resuelve empíricamente contra el listado de modelos de la cuenta.

## Objetivos del Usuario

- Como operador, quiero que producción use un modelo vivo disponible para mi cuenta y un SDK soportado, para que el E2E del ciclo #1 pueda ejecutarse.
- Como usuario final, quiero generar CVs y recibir sugerencias del copilot exactamente igual que antes — el cambio debe ser invisible.

## Alcance Estricto v1

### Incluye:
- **Descubrimiento de modelo (nuevo en v1.1):** listar los modelos disponibles para la cuenta con el SDK nuevo y resolver `TARGET_MODEL` por orden de preferencia escrito: `gemini-2.5-flash-lite` → `gemini-3.1-flash-lite` → `gemini-3-flash` (id exacto según el listado) → el Flash-Lite/Flash más económico disponible. La resolución ocurre en el gate de smoke, ANTES de tocar código, y se documenta con el id literal.
- `backend/requirements.txt`: `google-generativeai==0.8.3` → `google-genai==2.12.1`.
- `backend/app/services/llm_client.py`: reescritura de las llamadas al SDK preservando **intacta** la interfaz pública del módulo (mismas cuatro funciones `extract_job_title` / `extract_keywords` / `rewrite_bullets` / `generate_suggestion`, mismas excepciones tipadas, mismo mapeo 429→`LLMRateLimitError`); se conserva el patrón actual cliente-síncrono + executor y el parser tolerante a fences.
- Poblar `_MODEL_ALIASES`: `gemini-1.5-flash`, `gemini-2.0-flash`, `gemini-2.5-flash` — y `gemini-2.5-flash-lite` si `TARGET_MODEL` resulta distinto — todos → `TARGET_MODEL`. Cada resolución de alias emite warning en logs.
- `backend/app/config.py`: default de `GEMINI_MODEL` → `TARGET_MODEL`.
- `.env.example`: reflejar el nuevo default.
- Config var de Heroku actualizada a `TARGET_MODEL` y deploy desde la rama + re-test.

### NO incluye:
- Timeouts en llamadas externas (regla 6). Diferido con razón escrita: minimizar superficie para desbloquear el E2E; el SDK nuevo expone opciones HTTP de timeout que dejan el sprint de resiliencia a un paso. Deuda sigue registrada.
- Multi-proveedor / fallback OpenAI-Anthropic (siguiente ciclo si se justifica).
- Cambios en prompts, parsing, cv_engine, endpoints, frontend o Deepgram.
- Retries / circuit breakers (mismo criterio que timeouts).

## Comportamiento Esperado

### Flujo feliz:
1. Gate de smoke resuelve `TARGET_MODEL` y confirma 1 generación 200 contra él.
2. Backend con `google-genai` y `GEMINI_MODEL=TARGET_MODEL`: CV Engine hace sus 3 llamadas → 200 con `ats_score`; copilot SSE streamea `meta`/`chunk`/`done` — idéntico al comportamiento previo.
3. Modelo viejo en config → alias lo resuelve a `TARGET_MODEL` con warning — degradación silenciosa pero logueada.

### Casos edge:
- **Ningún modelo del orden de preferencia disponible** → detener el ciclo y reportar: decisión humana (cuenta/tier/proveedor). No improvisar modelos Pro ni preview restringidos.
- Modelo sin alias y no disponible → 404 → excepción tipada → error claro del endpoint (contrato actual); nunca crash.
- Excepción a mitad del stream SSE → cierre sin `done`; el frontend ya lo maneja (verificado en ciclo #1).
- `google-genai==2.12.1` con incompatibilidad → permitido pinear el 2.x estable más cercano funcional, reportado como desviación etiquetada.
- 429 → `LLMRateLimitError` → contrato actual (verificado en QA).
- Respuesta 3.x envuelta en fences markdown → `_strip_code_fences` ya lo tolera (verificado).

## Manejo de Errores

Sin cambios de contrato: los endpoints traducen las mismas excepciones tipadas a los mismos códigos HTTP de hoy. Nuevo en logs: warning de alias y el id del modelo activo al arrancar.

## Sistemas adyacentes (regla 10)

CV Engine y SSE consumen `llm_client` — cubiertos por preservación de interfaz. Audio/Deepgram: intocado. Pipeline Heroku: intocado (el build instala el pin nuevo sin cambios de Dockerfile). Costo: si `TARGET_MODEL` resuelve a la línea 3.x, el precio por token sube (~3× el de 2.5-lite) pero al volumen actual sigue en centavos; el tope de billing y quota caps ya activos lo contienen.

## Archivos afectados (estimado)

`backend/requirements.txt` · `backend/app/services/llm_client.py` · `backend/app/config.py` · `.env.example` — **nada más**.

## Definition of Done

- [ ] **AC-1.5-00** *(nuevo v1.1)* — Descubrimiento documentado: listado de modelos de la cuenta + `TARGET_MODEL` literal + 1 generación 200 contra él, antes de tocar código.
- [ ] **AC-1.5-01** — Smoke local (script efímero, no commiteado): los 4 caminos de `llm_client` (title, keywords, rewrite, suggestion streaming) contra Gemini con la key del `.env`, sin imprimir valores → todos exitosos antes de deployar.
- [ ] **AC-1.5-02** — Re-test en producción: generar CV → 200 con `ats_score` numérico (el mismo test que hoy da 500/404).
- [ ] **AC-1.5-03** — SSE en producción: `meta` + `chunk` progresivos + `done`.
- [ ] **AC-1.5-04** — Alias verificado en local: con un nombre de modelo viejo temporal, el log muestra la resolución a `TARGET_MODEL`; valor real restaurado al terminar.
- [ ] **AC-1.5-05** — Diff toca exactamente los 4 archivos del alcance; rama pusheada.
- [ ] **AC-1.5-06** — Logs del re-test sin errores nuevos (el warning de alias no cuenta).

## Verificación E2E

Sin E2E propio más allá del DoD: su verde **habilita** el E2E completo del Ciclo #1 (AC-03/04/05/06 + AC-08 de `migracion-monolito-heroku`), ejecutado inmediatamente después sobre la rama apilada. Verify audita la unión de ambos diffs; merges en cadena tras verify: `chore/heroku-migration` → `main`, luego `fix/gemini-sdk-migration` → `main`. Al cutover, HANDOFF §4 registra: SDK `google-genai`, `TARGET_MODEL` resuelto, churn de modelos de Google como riesgo recurrente con `_MODEL_ALIASES` como mitigación, y la decisión de privacidad del tier pagado.

---
*Changelog v1.1 (18 Jul 2026): evidencia nueva post-aprobación — log v12 con mensaje literal de gating para cuentas nuevas — convierte el modelo destino fijo (`gemini-2.5-flash-lite`) en resuelto empíricamente (`TARGET_MODEL`, AC-1.5-00) con orden de preferencia escrito y edge de detención si ninguno está disponible. Nada más cambia respecto a v1.0 aprobada.*
