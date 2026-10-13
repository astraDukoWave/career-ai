# Dictamen CTO: enmienda v1.2 del modo en vivo

- **Ciclo:** C2 (C2-SPEC-01 v1.2). Corrige el hallazgo de H-2 y prepara el
  modo micrófono para una llamada en altavoz.
- **Artefacto:** la rama `fix/live-mic-hold` (este PR) sobre `main` @ `0db81a1`.
- **Fecha:** 13 oct 2026. Skill: `cto-review` v0.2.
- **Firma:** Jonathan. Este dictamen no aprueba por él.

## Clasificación por acción

| Acción | Clase | Gate |
|---|---|---|
| Cambio en `turn_detector.py` (zona congelada): tope de 20 palabras a la continuación | Medio (comportamiento del modo en vivo; no toca Origin, límites, Deepgram ni secretos) | OK de Jonathan + este dictamen |
| Modo micrófono: tarjeta fija y barra de pregunta en espera | Rutina (solo frontend) | CI + E2E |
| `git push heroku main:main` | **Alto** (producción) | Firma de Jonathan |

## Verificaciones

| Claim | Fuente | Resultado |
|---|---|---|
| AC-13 sigue: Q2, Q4 y Q7 terminan en un solo turno con la pregunta completa | `test_turn_detector.py` con eventos reales de Nova-3 | [verified-this-session] |
| La sesión real completa sigue en 10 turnos | mismo archivo | [verified-this-session] |
| Un turno largo ya no se continúa (eventos reales de Q5, Q6 y Q7 juntados a 0.6 s), y sin el tope sí se habría continuado | tests nuevos | [verified-this-session] |
| Una introducción de más de 10 palabras sigue unida a la pregunta corta que la sigue | test nuevo (hallazgo de la revisión) | [verified-this-session] |
| Revisión independiente (subagente) sin bloqueantes. Sus 3 "should-fix" quedaron corregidos: la barra guarda 3 preguntas, el tope sube a 20 y la barra es fija | este PR | [verified-this-session] |
| Con el micrófono, la tarjeta de Q1 se queda y Q2 espera en la barra, completa | E2E en Chromium con el Deepgram falso | [verified-this-session] |
| La pestaña de la reunión sigue cambiando de tarjeta sola | Vitest (`cardPolicy.test.ts`); el E2E no puede capturar pestañas | [verified-this-session] (solo lógica) |
| No cambian el Origin, los límites, el cliente de Deepgram ni el protocolo del WebSocket | diff del PR | [verified-this-session] |
| El modo micrófono funciona con un teléfono en altavoz | prueba de humo de Jonathan antes de la llamada | [inherited-unverified] → condición 1 |

## Veredicto: APROBAR CON CAMBIOS

1. **Prueba de humo de 3 min después del deploy, antes de la llamada.**
   Usa el teléfono en altavoz con un video de preguntas de entrevista y
   responde en voz alta. *Por qué:* el E2E usa un micrófono falso, no la
   bocina de un teléfono.
2. **Hora límite.** Si a las 11:35 no está desplegado y probado, la llamada
   se hace sin la versión nueva. *Por qué:* un deploy a última hora no debe
   quitarle tiempo de preparación ni sumar estrés.

## Requisitos de alto riesgo

- **Rollback:** `heroku rollback -a career-ai` vuelve a la release actual
  (`ee9fef0`). No hay datos ni migraciones.
- **Blast radius:** solo el modo en vivo. El modo texto y el CV Engine no
  cambian.
- **Dueño:** Jonathan, que ejecuta el push y el rollback.
- **Observabilidad:** `heroku logs --tail -a career-ai` debe mostrar `Live
  session started` / `Live session ended` sin tracebacks.

## Transition packet

```yaml
phase: cto-review
cycle_id: C2
status: waiting_human
artifact: docs/reviews/c2-v12-cto-review.md
inputs: [main@0db81a1, C2-SPEC-01 v1.2, video de H-2]
outputs: [dictamen v1.2, condiciones 1-2]
evidence:
  verified_this_session: [pytest con eventos reales, Vitest, E2E con micrófono falso, diff sin cambios de seguridad]
  inherited_unverified: [modo micrófono con teléfono en altavoz]
deviations:
  - id: REQ-07-mic
    note: en el micrófono, cada pregunta después de la primera cuesta un clic
    disposition: ratify-with-reason
human_gates: [deploy v1.2, prueba de humo]
next_window_prompt: >
  Retoma CareerAI con HANDOFF.md. Si Jonathan usó la v1.2 en la llamada con
  Bull Rocket, revisa su resumen de sesión y heroku logs, y decide el
  siguiente paso del modo micrófono (diarización o karaoke) con esos datos.
```
