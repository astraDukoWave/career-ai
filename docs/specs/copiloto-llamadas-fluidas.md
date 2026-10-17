# Spec: copiloto-llamadas-fluidas

spec_id: C4-SPEC-01
Ciclo SDD #4 · Lane: **High-risk**. Toca la zona congelada del modo en vivo
y una API de pago (Deepgram).
Estado: **BORRADOR v0.2**, pendiente de aprobación de Jonathan.

Historial:
- **v0.1** (`01a10a4`).
- **Auditoría independiente de Codex** (17 oct): 4 bloqueos y 5 precisiones,
  todos atendidos aquí (tabla al final).
- **Decisión de Jonathan** (17 oct): la calibración de voz se hace en cada
  sesión.
- **Revisión de cómo resuelve esto el mercado:** el detalle vive en
  `strategy.md`, fuera del repo.

Ejecución: Codex abre un PR por change set; Claude corre `verify`; Jonathan
aprueba y despliega; Claude mergea. El `cto-review` es obligatorio antes del
deploy.
Corre en paralelo con C3-SPEC-01. Depende de los contratos compartidos que
fija el CS-0 de C3.
Skills aplicadas: `design-spec` + `system-design-spec` (reglas 0, 3, 6 y 10).

---

## Resumen general

En la primera entrevista real (13 oct, teléfono en altavoz, modo micrófono,
49 min), el copiloto de la v1.2 sirvió poco [evidencia: HANDOFF §2, PR #25]:
- Solo 1 de 3 tarjetas era una pregunta real.
- Dos tarjetas respondieron con la voz equivocada.
- 29 de las 39 entradas de la barra eran ruido.
- La tarjeta estuvo fuera de la pantalla en el 81 % de los cuadros.
- Deepgram escribió "Cloud" por Claude.

La v1.3 hace que, en modo micrófono, el copiloto:
1. separe la voz del candidato de la del entrevistador **antes** de armar
   turnos;
2. ignore muletillas y saludos;
3. responda siempre como el candidato;
4. muestre primero una pista corta en una tarjeta fija;
5. se adelante con seguridad cuando la pregunta ya está completa;
6. mida de verdad la latencia y las keyterms.

**Práctica del mercado** (detalle en `strategy.md`):
- Para entrevistas por teléfono, la herramienta líder usa justo este montaje
  (el teléfono en altavoz junto al micrófono de la laptop) con una muestra de
  voz del candidato para separar las voces.
- Las apps de escritorio, en cambio, separan por canal: el audio del sistema
  es el entrevistador y el micrófono es el candidato. En el navegador y en
  macOS 12 eso solo es posible con la pestaña de la reunión, que ya está
  resuelta.

## Objetivos del usuario

1. En una llamada en altavoz, el copiloto reacciona solo a lo que pregunta el
   entrevistador.
2. Entiendo la idea clave con un vistazo de 1 a 2 s, sin hacer scroll.
3. La pista aparece antes de que tenga que empezar a responder.

## Alcance estricto v1

**Incluye:**
- calibración por sesión en modo micrófono y separación de voces, con el
  método que elija el CS-0;
- turnos segmentados por hablante;
- filtro de muletillas y saludos;
- regla de perspectiva;
- pista + detalle;
- tarjeta fija;
- sugerencia anticipada con invalidación y presupuesto;
- métricas de latencia desde el fin acústico de la pregunta, más la
  cobertura de preguntas;
- keyterms medidas en tres niveles;
- consumidor SSE del MCP actualizado.

**NO incluye:**
- Practice Mode ni voz a voz;
- otro proveedor de STT o de LLM;
- separación en modo pestaña, que no la necesita;
- guardar audio o transcripciones en el servidor;
- una app de escritorio con captura del audio del sistema (fuera del
  navegador: backlog).

## Requisitos

- **REQ-01 · Calibración por sesión y separación de voces** (modo micrófono).
  - Al empezar, el candidato dice una frase de muestra de unos 5 s.
  - Se guarda solo la **huella** de esa muestra (estadísticas de rasgos) en
    memoria de la sesión. Nunca el audio. Se puede saltar.
  - **Método** (lo elige el CS-0):
    - **(a) Huella de banda en el servidor:** la proporción de energía entre
      4–7.5 kHz y 0.3–3.4 kHz por palabra o tramo, calculada sobre el PCM
      que ya llega.
      [hipótesis con datos preliminares: en la llamada del 13 oct la mediana
      fue −22 dB para el entrevistador y −46 dB para el candidato. Pero:
      solo hay cuartiles, no los rangos completos; es 1 llamada, con
      etiquetas aproximadas del OCR; y la grabación fue de QuickTime, no de
      Chrome con `noiseSuppression`.]
    - **(b) Diarización de Deepgram en streaming:** da `speaker` por
      palabra, y la muestra identifica cuál es el candidato.
      [supuesto: hay que verificar el soporte en streaming con Nova-3 multi
      y el costo. Según la auditoría, el streaming no trae
      `speaker_confidence`.]
  - **Confianza:** cada turno lleva una etiqueta (`candidate`, `interviewer`
    o `unknown`) y su confianza:
    - en (a), la distancia al umbral, medida en desviaciones de la huella de
      calibración;
    - en (b), la fracción de palabras del turno con la etiqueta mayoritaria.

    Los umbrales se fijan en el CS-0 con datos de calibración y se evalúan
    con datos **distintos**.
  - **AC-01:** ver el protocolo y los criterios del CS-0. Además, ninguna
    tarjeta nace de un turno etiquetado `candidate`.

- **REQ-02 · Segmentar por hablante antes de la continuación.**
  - El adaptador conserva la etiqueta de cada palabra o tramo.
  - El detector de turnos **corta el turno cuando cambia el hablante**.
  - La continuación v1.1 y v1.2 solo une pedazos del **mismo** hablante.
  - Un turno con hablantes mezclados o de baja confianza queda `unknown`.
  - **Después de una reconexión,** las etiquetas vuelven a `unknown` hasta
    que se identifica otra vez al candidato con la huella de calibración.
    Nunca se crean tarjetas automáticas con etiquetas viejas.
  - **AC-02:**
    - el caso que reprodujo la auditoría (el entrevistador pregunta "¿Qué
      stack usas?" y el candidato dice "Uso Python." 0.3 s después) da
      **dos** turnos, y solo el primero es pregunta con tarjeta;
    - con etiquetas `unknown` se conserva el comportamiento de la v1.2;
    - hay un test de reconexión.

    Las pruebas de turnos usan eventos reales grabados del proveedor (con
    `diarize` si gana el método b) o, para el método (a), audio sintético de
    dos fuentes. Nunca eventos inventados.

- **REQ-03 · Con voces separadas, el micrófono funciona como la pestaña.**
  - Con la calibración vigente, una pregunta del `interviewer` reemplaza la
    tarjeta sola.
  - `candidate` no hace nada.
  - `unknown` va a la barra de la v1.2.
  - **AC-03:** un E2E con un fixture sintético de dos voces lo prueba.

- **REQ-04 · Muletillas y saludos.**
  - No es pregunta de entrevista un turno que solo tiene:
    - una muletilla interrogativa: "¿vale?", "¿no?", "¿ok?", "¿sí?",
      "¿verdad?", "¿me explico?", "right?", "okay?";
    - o una cortesía: "¿cómo estás?", "¿me escuchas?".
  - "¿Qué stack usas, no?" sigue siendo pregunta.
  - **AC-04:** una tabla de casos en español y en inglés.

- **REQ-05 · Perspectiva.**
  - El prompt siempre habla como el candidato que le responde al
    entrevistador.
  - Si el texto no le pide nada al candidato, devuelve "sin pista" y no hay
    tarjeta.
  - Aplica también al modo texto.
  - **AC-05:** tests de contrato con un LLM falso, más una evaluación manual
    en local de 10 casos reales: 0 respuestas con la voz equivocada.

- **REQ-06 · Pista + detalle, y consumidores compatibles.**
  - Nuevo orden SSE:
    1. `meta`;
    2. `hint`: 2–3 viñetas de 12 palabras o menos;
    3. `chunk`* con el detalle;
    4. `error`?;
    5. `done`.
  - El frontend muestra `hint` arriba y el detalle plegado.
  - El consumidor SSE del MCP, que hoy solo acumula `chunk`, se actualiza
    para incluir el `hint`.
  - **AC-06:**
    - (a) un test de contrato del orden de eventos;
    - (b) el consumidor viejo del MCP sigue devolviendo texto no vacío con
      el stream nuevo;
    - (c) el consumidor nuevo incluye la pista.

- **REQ-07 · Tarjeta fija.**
  - La tarjeta queda fija arriba, la transcripción se puede plegar y la
    barra queda pegada a la tarjeta.
  - **AC-07:** un E2E con 30 turnos muestra la tarjeta siempre dentro del
    viewport.

- **REQ-08 · Sugerencia anticipada con invalidación.**
  - **Disparo:** un parcial del `interviewer` que termina en "?", tiene 4
    palabras o más y lleva 600 ms estable.
  - Las instrucciones sin "?" ("Cuéntame de tu proyecto.") esperan a que
    cierre el turno. Queda documentado.
  - Cada turno lleva una **revisión**, que sube con cada cambio de texto. La
    generación anticipada queda ligada a (turno, revisión, texto
    normalizado).
  - **Se publica solo si el texto final normalizado es *igual*** al
    anticipado. Ni prefijos ni parecidos.
  - Si no es igual:
    - se aborta el stream (AbortController);
    - se descarta todo resultado de una revisión vieja, aunque llegue tarde;
    - se regenera con el texto final.
  - **Presupuesto:**
    - máximo 1 anticipada por turno;
    - por sesión, las llamadas anticipadas no pasan de 1.5 × las preguntas
      ni de 60 en total;
    - al llegar al tope se apaga y queda anotado en el resumen.
  - **Cancelar del lado del cliente no garantiza** que el proveedor deje de
    generar. Los tokens se cuentan hasta el corte.
  - **AC-08:** tests para:
    - una instrucción sin interrogación;
    - un final que agrega una condición ("¿Qué stack usas… y por qué?");
    - una respuesta tardía de una revisión vieja que nunca se pinta;
    - el tope de presupuesto.

- **REQ-09 · Medición honesta.**
  - El mensaje `turn` suma el campo opcional `audio_end_s`: el fin acústico
    de la última palabra, en el reloj del audio.
  - El navegador ancla ese reloj al envío del primer frame (error esperado
    de ±100 ms, documentado) y calcula, por pregunta:
    - fin de la pregunta → primer texto visible;
    - fin de la pregunta → primera pista visible.
  - **Cobertura:** preguntas del entrevistador con tarjeta o en la barra,
    sobre el total de preguntas del entrevistador (anotado en las pruebas
    controladas). Evita que la precisión mejore solo porque se muestran
    menos tarjetas.
  - **La baseline se recalcula con este mismo método** en el CS-0: la ruta
    v1.2 contra la v1.3 sobre el mismo audio. El p50 de 1.0 s del 13 oct se
    midió desde el inicio de la sugerencia, no es comparable y solo queda
    como referencia.
  - **AC-09:** pruebas del cálculo con un reloj falso, y el resumen de
    sesión muestra las dos latencias más la cobertura.

- **REQ-10 · Keyterms: tres evidencias distintas.**
  - **(1) Enviadas:** el número de keyterms va en el log, nunca su texto.
  - **(2) Aceptadas:** la conexión abrió con keyterms, sin el reintento por
    HTTP 400. Va en el log.
  - **(3) Mejora medida:** la precisión en "Claude", "Anthropic", "MCP" y
    "CareerAI" sobre audio sintético, con y sin keyterms, con `multi`.
  - Si (3) no mejora, el CS-0 decide la alternativa; por ejemplo, el idioma
    fijo cuando el contexto está en español.
  - **AC-10:** un test por cada log de (1) y (2), y un reporte de (3) en el
    dictamen del CS-0.

- **REQ-11 · Sesión obligatoria** (contrato con C3).
  - El WebSocket en vivo exige sesión, porque C3 lo implementa.
  - Los E2E de C4 usan el helper de login falso del CS-0 de contratos.
  - **AC-11:** los E2E en verde con login falso.

- **NFR-01 · Latencia:** p90 de 1.5 s o menos entre el fin de la pregunta y
  la primera pista visible.
- **NFR-02 · Costo:**
  - el presupuesto de REQ-08;
  - la diarización (si gana) con su precio verificado en el cto-review;
  - el resumen cuenta las llamadas y los tokens.
- **NFR-03 · Privacidad:**
  - la grabación del 13 oct (voz de un tercero) y las pruebas controladas
    **nunca** entran al repo;
  - la evaluación local escribe solo métricas agregadas;
  - los fixtures versionados son sintéticos.
- **NFR-04 · Compatibilidad:**
  - campos nuevos opcionales (`speaker`, `confidence`, `revision`,
    `audio_end_s`, evento `hint`);
  - se mantienen el Origin y los límites.
- **NFR-05 · Sin regresiones** en modo pestaña ni en modo texto (los E2E
  actuales siguen en verde).

### Decisiones de diseño (system-design-spec)

- **Escala:** sin cambio. 1 sesión activa, con tope de 2.
- **Protocolo:** el WebSocket sigue para el audio y el SSE para las
  sugerencias, con campos y eventos opcionales.
- **Resiliencia:**
  - sin etiqueta confiable → `unknown` → barra de la v1.2;
  - generación anticipada cancelable y con presupuesto;
  - falla de la diarización → método (a) o modo seguro.
- **Sistemas adyacentes:**
  - modo texto (prompt compartido);
  - MCP (consumidor SSE);
  - C3 (sesión y `projects` en el contexto).

## CS-0 · Elegir el método de separación (decisión con datos)

**Protocolo:**
- Jonathan hace pruebas controladas con un guion: una persona o una
  grabación de prueba hace de entrevistador desde un teléfono en altavoz, y
  él responde.
- Usa un build instrumentado que registra **solo** métricas por turno: los
  rasgos, la etiqueta de cada método y la etiqueta humana, que él anota con
  el guion.
- **Sesión 1 = calibración** de umbrales. **Sesiones 2 a 4 = evaluación.**
- Condiciones:
  - distancia del teléfono a la Mac: 30, 60 y 100 cm;
  - volumen bajo y alto;
  - con y sin ruido de fondo;
  - con y sin hablar encima.
- La grabación del 13 oct solo sirve como chequeo secundario, en local,
  porque sus etiquetas son aproximadas.

**Reporte por voz, no global:**
- recall y precisión del `interviewer` y del `candidate`;
- preguntas detectadas y omitidas;
- % de turnos que van al respaldo (`unknown`);
- latencia y cobertura (REQ-09).

**Criterio para aprobar un método:**
- recall de preguntas del entrevistador de 90 % o más;
- turnos del candidato etiquetados como entrevistador en 5 % o menos;
- respaldo en 20 % o menos.

Si los dos pasan, gana el de menor costo y menor latencia.

**Si ninguno pasa:** la v1.3 sale con todo lo demás (REQ-04 a REQ-10) y con
la separación apagada (comportamiento de la v1.2). La separación vuelve al
backlog con la alternativa de una app de escritorio o de captura por canal.

**AC-01 = el dictamen del CS-0** con estos números, más la regla de "ninguna
tarjeta desde `candidate`".

## Comportamiento esperado

### Flujo feliz (modo micrófono)

1. Start → frase de muestra → "Calibrado".
2. El entrevistador pregunta. Su turno es `interviewer` con confianza alta, y
   la anticipada arranca si termina en "?".
3. La pista aparece arriba, y el detalle queda plegado.
4. El candidato responde. Su turno es `candidate`, y no pasa nada.
5. La siguiente pregunta reemplaza la tarjeta sola.

### Casos edge

- **EDGE-01 · Calibración saltada:** todo es `unknown` y se comporta como la
  v1.2.
- **EDGE-02 · Los dos hablan a la vez:** el turno queda mezclado → `unknown`
  → va a la barra.
- **EDGE-03 · Entra otro entrevistador:** no es `candidate`, porque solo se
  calibra al candidato.
- **EDGE-04 · El candidato lee la pista en voz alta:** es `candidate`, y no
  pasa nada.
- **EDGE-05 · Reconexión:** las etiquetas pasan a `unknown` hasta
  re-identificar.
- **EDGE-06 · La pregunta cambia al final:** se aborta, se descarta y se
  regenera.
- **EDGE-07 · Deepgram rechaza `diarize` o las keyterms:** queda en el log y
  se sigue sin esa función.
- **EDGE-08 · Se agota el presupuesto de anticipadas:** se apaga la
  anticipada y la sesión sigue normal.

## Manejo de errores

- **Lo que ve el usuario:**
  - "No pude calibrar tu voz; sigo en modo seguro (tú eliges cada
    pregunta)."
  - Los mensajes actuales del modo en vivo siguen igual.
- **Lo que se registra:**
  - el resultado de la calibración (sin audio);
  - los turnos por etiqueta y confianza;
  - las anticipadas usadas, descartadas y el tope;
  - las tres evidencias de las keyterms.

## Supuestos y decisiones abiertas

- [supuesto] La diarización de Deepgram funciona en streaming con Nova-3
  `multi`; hay que confirmar el formato de `speaker` y que no trae
  confianza. Se verifica en el CS-0.
- [hipótesis] Con las voces separadas, al menos el 80 % de las tarjetas son
  preguntas reales, con una cobertura del 90 % o más.
- [evidencia] El detector actual une al entrevistador y al candidato en un
  solo turno con `is_question=True` (el caso de AC-02, reproducido el 17
  oct) [verified-this-session].
- [evidencia] El consumidor SSE del MCP solo acumula `chunk`
  (`mcp/careerai_mcp/server.py`) [verified-this-session].
- **Decidido (Jonathan, 17 oct):** la calibración se hace en cada sesión.
  Reusar la huella entre sesiones queda como trigger: si recalibrar molesta
  en 3 llamadas reales, se evalúa guardar solo la huella por dispositivo.

## Riesgo por acción

| Acción | Clase | Gate |
|---|---|---|
| Cambios en `turn_detector.py`, `live_session.py`, `stt_stream.py` e `interview_audio.py` | Alto (zona congelada, API de pago) | Este spec + verify + cto-review |
| `diarize` en Deepgram (costo) | Medio | Precio verificado en el cto-review |
| Prompt nuevo (también afecta el modo texto) | Medio | E2E + evaluación manual |
| Pruebas controladas con voz de otra persona | Medio (privacidad) | Consentimiento de quien participe; nada entra al repo |
| Deploy | Alto | Firma de Jonathan |

## Release, rollback y evidencia

- **Release:** dictamen del CS-0 → cto-review → deploy de Jonathan → prueba
  real con el teléfono en altavoz y calibración.
- **Rollback:** `heroku rollback -a career-ai`. No hay datos persistentes.
- **Evidencia:**
  - pytest (eventos reales grabados y audio sintético);
  - Vitest;
  - E2E;
  - dictamen del CS-0 con sus métricas por voz.

## Métricas de resultado

| Métrica | Fuente | Baseline | Review | Decisión |
|---|---|---|---|---|
| % de tarjetas que son preguntas reales del entrevistador (precisión) | Resumen + anotación | 33 % (13 oct) | Tras 3 llamadas reales | ≥ 80 %: continuar |
| Cobertura de preguntas del entrevistador | Resumen + anotación | Se recalcula en el CS-0 | Tras 3 llamadas | ≥ 90 % |
| Fin acústico → primera pista visible (p50 / p90) | Resumen (REQ-09) | Se recalcula en el CS-0 con el mismo método | Tras 3 llamadas | p50 ≤ 0.5 s y p90 ≤ 1.5 s |
| % de turnos al respaldo (`unknown`) | Resumen | n/a | Tras 3 llamadas | ≤ 20 % |

## Archivos afectados (estimación, no contrato)

- **Backend:**
  - `app/services/stt_stream.py` (etiqueta por palabra, `diarize`, logs de
    keyterms);
  - `app/services/live_session.py` (calibración y rasgos de banda);
  - `app/services/turn_detector.py` (segmentación por hablante, `unknown`,
    revisiones, muletillas);
  - `app/api/interview_audio.py` (mensajes de calibración);
  - `app/services/llm_client.py` (perspectiva, pista + detalle);
  - `app/api/interview.py` (evento `hint`);
  - tests y fixtures sintéticos.
- **Frontend:**
  - `components/LiveInterview.tsx`;
  - `lib/cardPolicy.ts`, `lib/liveTranscript.ts` y `lib/sessionSummary.ts`
    (latencias y cobertura);
  - `hooks/useLiveAudio.ts` (ancla del reloj);
  - `api/client.ts`.
- **MCP:** el consumidor SSE en `careerai_mcp/server.py` y sus tests.
- **E2E:** `e2e/` (dos voces, tarjeta fija, login falso).
- **Docs:** C2-SPEC-01 marcado como reemplazado en REQ-04 y REQ-07,
  `HANDOFF.md` y `STATE.md`.
- **Coordinación:** ver "Contratos compartidos" en C3-SPEC-01. El CS-0 de
  contratos de C3 se mergea antes que cualquier PR de este spec.

## Definition of Done

- [ ] Dictamen del CS-0 con métricas por voz y el método elegido, o la
      separación apagada si ninguno pasa.
- [ ] AC-02 a AC-11 cubiertos, con la CI en verde, incluidos los E2E de modo
      pestaña y modo texto sin regresiones.
- [ ] Latencia y cobertura medidas con el método de REQ-09 en una prueba
      controlada.
- [ ] cto-review firmado antes del deploy.
- [ ] Prueba real de Jonathan después del deploy.
- [ ] `HANDOFF.md` y `STATE.md` actualizados.

## Auditoría de Codex (17 oct) → cómo se atiende

| # | Hallazgo | Dónde se atiende |
|---|---|---|
| 8 | La huella de banda es una hipótesis | REQ-01 lo dice así; el CS-0 separa calibración y evaluación, usa la captura real de Chrome, prueba condiciones, reporta por voz y define qué pasa si ningún método pasa |
| 9 | Hablantes mezclados en un turno | REQ-02: segmentar antes de la continuación, `unknown`, reconexión y el caso reproducido como AC |
| 10 | La anticipada reutiliza respuestas equivocadas | REQ-08: revisiones, igualdad exacta, descarte de lo tardío y presupuesto, con los casos pedidos |
| 11 | La métrica no mide desde el fin acústico | REQ-09: `audio_end_s`, primer texto y primera pista, cobertura y baseline recalculada |
| + | `speaker_confidence` no existe en streaming | REQ-01: confianza definida por método; se verifica en el CS-0 |
| + | El consumidor SSE del MCP | REQ-06 + AC-06 (b, c) |
| + | Tres evidencias distintas de keyterms | REQ-10 |
| + | Specs paralelos contra implementación paralela | REQ-11 + los contratos compartidos de C3 |
