# Dictamen CTO: deploy del copiloto en vivo — gate D-2

- **Ciclo:** C2 (C2-SPEC-01 v1.1, C2-PLAN-01), change set CS-7.
- **Artefacto revisado:** `main` @ `31a1139` (PRs #16, #17, #19, #20 y #21
  sobre la producción actual v20 = `04b8f5d`).
- **Fecha:** 1 oct 2026. Skill: `cto-review` v0.2.
- **Firma:** Jonathan. Este dictamen no aprueba por él.

## Clasificación por acción

| Acción | Clase | Gate |
|---|---|---|
| `git push heroku main:main` (release nueva de toda la app) | **Alto** (producción) | D-2, firma de Jonathan |
| Nuevo WebSocket que reenvía audio a Deepgram (API de pago) | **Alto** (dinero) | D-2 + límites de NFR-05 |
| Comando de arranque nuevo en `heroku.yml` (1 worker, frames de 1 MiB, sin compresión) | **Alto** (afecta a toda la app) | D-2; la CI arranca la imagen con ese comando |
| Logs INFO de `app.*` con la IP del cliente | Rutina (sin texto del usuario) | PR #17 |
| Frontend nuevo (modo en vivo, resumen) | Rutina | PRs #19 y #20 + E2E |

## Verificaciones (matriz)

| Claim | Fuente | Resultado |
|---|---|---|
| CI completa en verde en cada PR del ciclo, incluido el E2E | API de GitHub, checks de #16–#21 | [verified-this-session] |
| La imagen de producción construye y arranca con el comando nuevo de `heroku.yml` | Job `production image · build + boot`, que lee el comando del archivo | [verified-this-session] |
| El Origin ajeno se rechaza antes de abrir Deepgram (HTTP 403) | `test_live_server.py` con uvicorn real | [verified-this-session] |
| Máximo 2 sesiones y 90 min; un socket sin `start` no ocupa cupo | `test_live_ws.py` | [verified-this-session] |
| Un frame enorme no infla la memoria (cap de 1 MiB, sin deflate) | Revisión independiente de #17: 6 sockets maliciosos suman ~24 MiB (antes, 639 MiB) | [verified-this-session] |
| La key de Deepgram no llega al navegador | Test de backend, grep del bundle en la CI y el E2E: la página solo habla con la app | [verified-this-session] |
| Una pregunta cortada termina en una sola sugerencia con la pregunta completa | Eventos reales de Nova-3 (PR #18) en pytest, y el E2E en Chromium | [verified-this-session] |
| Con Deepgram caído, el modo texto sigue | E2E `test_with_deepgram_down_the_text_mode_still_answers` | [verified-this-session] |
| `CORS_ORIGINS` en Heroku incluye `https://career-ai-95daf7c9a813.herokuapp.com` | HANDOFF §9 (documentado, no leído de Heroku) | [inherited-unverified] → condición 1 |
| `DEEPGRAM_API_KEY` está en las Config Vars de Heroku | Set de secretos del 29 sep (H-1) | [inherited-unverified] → condición 1 |
| La cuenta de Deepgram tiene crédito | Supuesto del spec | [inherited-unverified] → condición 2 |
| La pestaña de Meet comparte audio en Chrome 150 / macOS 12 | Supuesto técnico NFR-07 | [inherited-unverified] → H-2 |

## Veredicto: APROBAR CON CAMBIOS

Los cambios son verificaciones previas al push. No hace falta tocar código.

1. **Confirmar dos Config Vars antes del push.** Que `CORS_ORIGINS` incluya
   el dominio de Heroku y que exista `DEEPGRAM_API_KEY`. Si el origen falta,
   el modo en vivo rechaza a su propio frontend (403) y el resto de la app
   sigue normal; si falta la key, el modo en vivo muestra "no disponible".
   *Por qué:* son los dos únicos datos que el dictamen no puede ver desde
   aquí.
2. **Poner una alerta de uso en la consola de Deepgram** (por ejemplo, a
   USD 5). *Por qué:* no hay autenticación hasta Phase 3. Los límites acotan
   el gasto, pero no a quién lo genera (ver la decisión 1).

## Requisitos de alto riesgo

- **Rollback:** `heroku rollback -a career-ai` vuelve a v20 (`04b8f5d`).
  - La release de Heroku incluye la imagen y el comando de arranque, así
    que el rollback restaura ambos.
  - No hay migraciones de datos ni estado en el servidor. Es reversible por
    construcción.
- **Blast radius:**
  - Si falla el modo en vivo, el modo texto y el CV Engine no dependen de
    él (NFR-06; probado en el E2E).
  - Si fallara el arranque, se cae toda la app: es un solo dyno. Lo
    mitiga que la CI arranca exactamente esta imagen con este comando, y
    `/health` lo detecta en segundos.
  - **Peor caso de costo:** 2 sesiones abusivas las 24 h ≈ 2 × 24 h × USD
    0.35/h ≈ USD 17 al día en Deepgram, más Gemini.
- **Dueño:** Jonathan (ejecuta el push y el rollback). Claude prepara el
  diagnóstico.
- **Observabilidad** (en `heroku logs --tail -a career-ai`):
  - `Live session started: client=… source=… keyterms=…` y `Live session
    ended: … reason=… duration=… turns=… questions=…`.
  - `Live WS refused: origin …` o `… sessions already active`.
  - `Deepgram live connection dropped (code=…)`.
  - En la consola de Deepgram, el uso queda etiquetado `careerai-live`.
  - Señales de alarma: `reason=stt_unavailable` repetido, H12/H15/R14, o
    tracebacks (AC-11).

## Decisiones que son tuyas

1. **¿Despliegas sin login, con los límites actuales como única protección
   de costo?**
   - *TL;DR:* cualquiera que conozca la URL podría ocupar las 2 sesiones y
     gastar crédito de Deepgram. El tope por sesión es de 90 min.
   - *Ganas:* pruebas en entrevistas reales ya. *Pagas:* hasta ~USD 17 al
     día en el peor caso, hasta que llegue la autenticación.
   - *Recomendación:* sí, con la alerta de uso de la condición 2 y revisando
     los logs la primera semana.
   - **Pregunta cerrada:** ¿aceptas ese riesgo de costo para el piloto? (sí/no)

## Mensaje de aprobación (pegar en la ventana del ciclo)

> Apruebo el gate D-2. Autorizo el deploy de `main` @ `31a1139` a Heroku
> (`career-ai`). Ya confirmé `CORS_ORIGINS` y `DEEPGRAM_API_KEY`, y puse
> una alerta de uso en Deepgram. Acepto el riesgo de costo sin login
> durante el piloto. El rollback es `heroku rollback -a career-ai`.

## Registro del gate

```json
{
  "gate_id": "C2-D2",
  "cycle_id": "C2",
  "artefacto": "main@31a1139 (docs/reviews/c2-d2-cto-review.md)",
  "veredicto": "APROBAR CON CAMBIOS",
  "condiciones": ["Config Vars CORS_ORIGINS y DEEPGRAM_API_KEY confirmadas", "alerta de uso en Deepgram"],
  "respuesta_humana": "aprobado; desplegado por Jonathan el 1 oct 2026 (04b8f5d..ee9fef0, /health 200)"
}
```

**Resultado del gate (1 oct 2026):**
- Condición 1: cumplida. Jonathan confirmó `CORS_ORIGINS` (incluye el
  dominio de Heroku) y que `DEEPGRAM_API_KEY` existe.
- Condición 2: **sustituida**. Deepgram no ofrece una alerta de uso
  configurable que se haya podido confirmar; solo un correo cuando el
  crédito baja y el interruptor de Auto-reload. El tope de gasto pasa a ser
  el saldo prepagado con **Auto-reload apagado**: si alguien abusa, el modo
  en vivo se detiene al acabarse el saldo y no hay cargo sorpresa.
- Decisión 1: sí, con la URL sin difundir. El login entra al Ciclo #3.

## Transition packet

```yaml
phase: cto-review
cycle_id: C2
status: done (D-2 desplegado; H-2 y H-MCP hechos; H-3 pendiente)
artifact: docs/reviews/c2-d2-cto-review.md
inputs: [main@31a1139, C2-SPEC-01 v1.1, C2-PLAN-01]
outputs: [dictamen D-2, condiciones 1-2, decisión 1]
evidence:
  verified_this_session: [CI #16-#21, boot de la imagen con heroku.yml, E2E, tests de Origin/límites/memoria, AC-12, AC-13 con eventos reales]
  inherited_unverified: [CORS_ORIGINS en Heroku, DEEPGRAM_API_KEY en Heroku, crédito de Deepgram, audio de pestaña en Chrome 150/macOS 12]
deviations:
  - id: EDGE-10
    note: el navegador ve HTTP 403 (1006), no 1008, porque el Origin se rechaza antes de accept() (NFR-04)
    disposition: ratify-with-reason
  - id: H-2-order
    note: H-2 (prueba de pestaña) se mueve a después de D-2, como pidió el /goal del 30 sep
    disposition: ratify-with-reason
human_gates: [D-2, H-2, H-3, H-MCP]
next_window_prompt: >
  Retoma CareerAI con HANDOFF.md. Si Jonathan aprobó D-2 y desplegó, revisa
  `heroku logs` contra la sección de observabilidad de
  docs/reviews/c2-d2-cto-review.md, guía H-2 y H-3, y calibra
  TURN_CONTINUATION_S con su resumen de sesión. Si no, espera su decisión.
```
