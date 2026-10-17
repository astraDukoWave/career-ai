# Spec: copiloto-llamadas-fluidas

spec_id: C4-SPEC-01
Ciclo SDD #4 · Lane: **High-risk**. Toca la zona congelada del modo en vivo
y una API de pago (Deepgram).
Estado: **BORRADOR**, pendiente de aprobación de Jonathan.
Ejecución: Codex abre un PR por change set; Claude corre `verify`; Jonathan
aprueba y despliega; Claude mergea con merge commit y SHA fijado. Antes del
deploy hace falta un `cto-review` (regla de CLAUDE.md para la zona congelada).
Corre en paralelo con C3-SPEC-01 (perfil vivo desde GitHub).
Skills aplicadas: `design-spec` + `system-design-spec` (reglas 0, 3, 6 y 10).

---

## Resumen general

En la primera entrevista real (13 oct, llamada por teléfono en altavoz,
modo micrófono, 49 min), el copiloto de la v1.2 hizo lo que estaba diseñado
para hacer, pero sirvió poco [evidencia: HANDOFF §2, PR #25]:
- De 3 tarjetas, solo 1 era una pregunta real del entrevistador, y llegó
  unos 90 s tarde.
- Dos tarjetas respondieron con la voz equivocada: una como si el candidato
  fuera el entrevistador, la otra como si fuera la empresa.
- La barra tuvo 39 entradas: 10 preguntas reales, 18 muletillas o
  afirmaciones y 11 frases del propio candidato.
- La tarjeta estuvo fuera de la pantalla en el 81 % de los cuadros.
- La pausa mediana fue de 0.51 s, pero la primera palabra de la sugerencia
  llegaba en 1.0 s (p50).
- Deepgram escribió "Cloud" por Claude y "API de Tropic" por Anthropic.

La v1.3 hace que el copiloto, en modo micrófono:
1. distinga al candidato del entrevistador e ignore los turnos del
   candidato;
2. no trate muletillas ni saludos como preguntas;
3. responda siempre como el candidato;
4. muestre primero una pista corta, en una tarjeta que no se va de la
   pantalla;
5. empiece a generar antes de que cierre el turno cuando la pregunta ya está
   completa;
6. confirme que las palabras clave (keyterms) llegan a Deepgram.

## Objetivos del usuario

1. En una llamada en altavoz, el copiloto reacciona solo a lo que pregunta el
   entrevistador, nunca a lo que digo yo.
2. Entiendo la idea clave con un vistazo de 1 a 2 segundos, sin hacer
   scroll.
3. La pista aparece antes de que tenga que empezar a responder.

## Alcance estricto v1

**Incluye:**
- separación de voces en modo micrófono, con el método que elija el CS-0;
- filtro de muletillas y saludos;
- regla de perspectiva en el prompt de sugerencia;
- formato pista + detalle;
- tarjeta fija y transcripción plegable;
- sugerencia anticipada;
- verificación de las keyterms;
- evaluación local con la grabación del 13 oct, sin versionarla.

**NO incluye:**
- Practice Mode ni voz a voz;
- cambiar de proveedor de STT o de LLM;
- separación de voces en modo pestaña (la pestaña solo trae al
  entrevistador);
- guardar audio o transcripciones en el servidor;
- idiomas distintos de inglés y español.

## Requisitos

- **REQ-01 · Separación de voces en modo micrófono.**
  - **Calibración:** al empezar en modo micrófono, el candidato dice una
    frase de muestra de unos 5 s ("Hola, soy Jonathan y estoy listo"). Se
    puede saltar.
  - **Etiquetado:** durante la sesión, cada turno se marca `candidate` o
    `interviewer`. Los turnos del candidato nunca crean tarjetas ni entradas
    en la barra. Se ven en la transcripción con otro estilo.
  - **Método:** lo decide el CS-0 entre dos candidatos:
    - **(a) Huella de banda en el servidor.** Se calcula sobre el mismo PCM
      de 16 kHz que ya llega: la proporción de energía entre 4–7.5 kHz y
      0.3–3.4 kHz en el tramo de cada turno, contra un umbral calibrado con
      la frase de muestra.
      [evidencia preliminar, spike del 17 oct sobre el audio de la llamada
      del 13 oct: mediana de −22 dB para el entrevistador contra −46 dB para
      el candidato, cuartiles sin traslape, histograma bimodal. Solo es 1
      llamada, con etiquetas aproximadas del OCR y otra ruta de audio
      (QuickTime, no Chrome con `noiseSuppression`).]
    - **(b) Diarización de Deepgram en streaming (`diarize`).** La frase de
      muestra identifica qué etiqueta es el candidato.
      [supuesto: hay que verificar que funcione en streaming con Nova-3
      `language=multi`, que las etiquetas sean estables y cuánto cuesta]
  - **Criterio de decisión del CS-0:** que etiquete bien al menos el 90 % de
    los turnos. Si los dos cumplen, gana el de menor costo y menor latencia;
    (a) no cuesta nada extra.
  - **Sin calibración, o con confianza baja:** se mantiene el
    comportamiento de la v1.2 (tarjeta fija y barra).
  - **AC-01:** en la evaluación local se etiqueta correctamente al menos el
    90 % de los turnos, y ninguna tarjeta nace de un turno del candidato.

- **REQ-02 · Con las voces separadas, el micrófono funciona como la
  pestaña.**
  - Con la calibración vigente, una pregunta del entrevistador reemplaza la
    tarjeta sola (como en la pestaña). Los turnos del candidato no hacen
    nada.
  - La barra de la v1.2 queda como respaldo cuando la confianza es baja.
  - **AC-02:** un E2E con un fixture sintético de dos voces muestra que las
    preguntas del entrevistador cambian la tarjeta sin clic, y que las
    frases del candidato no la cambian.

- **REQ-03 · Muletillas y saludos.**
  - No es pregunta de entrevista un turno que solo tiene:
    - una muletilla interrogativa: "¿vale?", "¿no?", "¿ok?", "¿sí?",
      "¿verdad?", "¿me explico?", "right?", "okay?";
    - o una cortesía: "¿cómo estás?", "¿me escuchas?", "¿me oyes bien?".
  - Una pregunta real que termina con muletilla sigue siendo pregunta:
    "¿Qué stack usas, no?".
  - **AC-03:** tabla de casos en español e inglés. Incluye las formas que se
    vieron el 13 oct, reescritas sin datos de terceros. Las pruebas de
    turnos siguen usando eventos reales grabados del proveedor (decisión
    cerrada).

- **REQ-04 · Perspectiva.**
  - El prompt de sugerencia siempre habla como el candidato que le responde
    al entrevistador. Nunca con la voz de la empresa ni del entrevistador.
  - Si el texto no le pide nada al candidato (una afirmación, o una pregunta
    del propio candidato), el modelo devuelve "sin pista" y no aparece
    tarjeta.
  - **AC-04:**
    - tests de contrato del prompt con un LLM falso;
    - evaluación manual en local de 10 casos reales de la llamada, con
      resultado en el dictamen: ninguna respuesta con la voz equivocada.

- **REQ-05 · Pista + detalle.**
  - Primero vienen 2 o 3 viñetas de 12 palabras o menos (la pista). Después,
    el detalle, plegado.
  - El stream SSE manda la pista primero, como un evento nuevo y opcional.
    Los clientes viejos siguen funcionando.
  - **AC-05:** un test de contrato del stream comprueba que el evento de la
    pista llega antes que el detalle.

- **REQ-06 · Tarjeta fija.**
  - La tarjeta queda fija arriba y siempre visible mientras la transcripción
    se desplaza.
  - La transcripción se puede plegar, y la barra de espera queda pegada a la
    tarjeta.
  - **AC-06:** en un E2E con 30 turnos de transcripción, la tarjeta sigue
    dentro del viewport.

- **REQ-07 · Sugerencia anticipada.**
  - Si un parcial ya se lee como pregunta completa (termina en "?" y tiene 4
    palabras o más) y se mantiene estable 400 ms, se empieza a generar.
  - Si el turno cierra con ese texto, o con uno que lo empieza igual, la
    pista ya está lista. Si el texto cambia, se cancela y se vuelve a
    generar.
  - Solo puede haber una generación anticipada en vuelo.
  - **AC-07:** en la evaluación local, p50 de 0.5 s o menos entre el fin de
    la pregunta y la primera palabra de la pista (baseline real: p50 1.0 s).

- **REQ-08 · Keyterms.**
  - Al abrir la conexión, el log dice cuántas keyterms aceptó Deepgram, o si
    hubo que reintentar sin ellas (ese reintento ya existe con una
    advertencia; los logs del 13 oct ya no están).
  - El CS-0 mide, con audio sintético, si las keyterms corrigen "Claude",
    "Anthropic", "MCP" y "CareerAI" con `language=multi`. Si no, decide la
    alternativa; por ejemplo, el idioma fijo cuando el contexto es en
    español.
  - **AC-08:** un test cubre el log de los dos caminos y no imprime las
    keyterms (pueden contener datos del CV).

- **NFR-01 · Latencia:** p90 de 1.5 s o menos entre el fin de la pregunta y
  la pista.
- **NFR-02 · Costo:**
  - la sugerencia anticipada no puede pasar del doble de llamadas al LLM por
    sesión, y el resumen de la sesión las cuenta;
  - si la diarización de Deepgram cuesta extra, el cto-review lo dice.
- **NFR-03 · Privacidad.**
  - La grabación del 13 oct y todo lo que salga de ella nunca entran al
    repo, porque contiene la voz de un tercero. La evaluación local solo
    escribe métricas agregadas.
  - Los fixtures versionados son sintéticos (TTS), como en el CS-0 del
    Ciclo #2.
- **NFR-04 · Seguridad y límites.**
  - Se mantienen el chequeo de Origin, las 2 sesiones y los 90 min.
  - El protocolo cambia solo hacia atrás compatible: campo nuevo y opcional
    `speaker` en `partial`, `final` y `turn`, y un evento nuevo para la
    pista.
- **NFR-05 · Sin regresiones en modo pestaña:** el E2E actual sigue en
  verde.

### Decisiones de diseño (system-design-spec)

- **Escala (regla 0):** sin cambio. `dimension`: sesiones en vivo
  simultáneas; `current_value`: 1; tope de 2 por diseño (NFR-05 del
  Ciclo #2).
- **Protocolo (regla 3):** sigue el WebSocket para el audio y el SSE para
  las sugerencias. Solo se suman campos opcionales.
- **Resiliencia (regla 6):**
  - si la diarización o el cálculo de banda fallan, el turno queda "sin
    etiqueta" y aplica el respaldo de la v1.2;
  - la generación anticipada se cancela sin dejar estado.
- **Sistemas adyacentes (regla 10):**
  - el prompt nuevo se comparte con el modo texto: la regla de perspectiva
    también le aplica, y su E2E lo cubre;
  - el contexto del CV cambiará con C3 (sección Proyectos). Este spec solo
    lo lee.

## Comportamiento esperado

### Flujo feliz (modo micrófono)

1. El candidato elige Microphone, presiona Start y dice la frase de muestra
   ("Calibrado").
2. El entrevistador pregunta. Su turno queda `interviewer` y es pregunta.
3. La pista aparece en 0.5 s o menos: 3 viñetas arriba y el detalle plegado.
4. El candidato responde. Sus turnos quedan `candidate`, no crean tarjeta y
   se ven en gris en la transcripción.
5. La siguiente pregunta del entrevistador cambia la tarjeta sola.

### Casos edge

- **EDGE-01 · Calibración saltada:** se comporta como la v1.2 (tarjeta fija
  y barra).
- **EDGE-02 · Los dos hablan a la vez:** el turno se etiqueta por la voz
  dominante. Si la confianza es baja, va a la barra.
- **EDGE-03 · Cambia el entrevistador** (otra persona entra a la llamada):
  sigue sin ser el candidato, porque solo el candidato se calibra.
- **EDGE-04 · El candidato lee la pista en voz alta:** el turno es
  `candidate` y no hace nada.
- **EDGE-05 · Ruido, o el teléfono sin altavoz:** la confianza baja y aplica
  el respaldo de la v1.2.
- **EDGE-06 · Pregunta anticipada que cambia al final:** se cancela y se
  regenera. Nunca quedan dos pistas.
- **EDGE-07 · Deepgram rechaza `diarize` o las keyterms:** se registra y se
  sigue sin esa función.

## Manejo de errores

- **Lo que ve el usuario:**
  - "No pude calibrar tu voz; sigo en modo seguro (tú eliges cada
    pregunta)."
  - Los mensajes actuales del modo en vivo siguen igual.
- **Lo que se registra:**
  - el resultado de la calibración (sin audio);
  - el conteo de turnos por etiqueta;
  - el número de generaciones anticipadas usadas y canceladas;
  - el estado de las keyterms.

## Supuestos y decisiones abiertas

- [supuesto] La huella de banda de la llamada del 13 oct se reproduce en la
  ruta real: Chrome a 16 kHz con `noiseSuppression: true`. El CS-0 lo mide
  con una prueba controlada de 3 min de Jonathan (su teléfono en altavoz con
  otra persona o con un audio de prueba) y un build que registra solo las
  métricas de banda por turno.
- [supuesto] Deepgram ofrece diarización en streaming con Nova-3 `multi`. Se
  verifica en la documentación (en esta sesión no pude abrirla) y con una
  prueba.
- [hipótesis] Con las voces separadas, al menos el 80 % de las tarjetas son
  preguntas reales (baseline: 1 de 3).
- **Decisión abierta (Jonathan):** si la calibración se pide en cada sesión
  o se recuerda por dispositivo (localStorage, solo el umbral, nunca el
  audio). Mi propuesta: en cada sesión, porque el teléfono, la sala y la
  distancia cambian.

## Riesgo por acción

| Acción | Clase | Gate |
|---|---|---|
| Cambios en `turn_detector.py`, `live_session.py`, `stt_stream.py` e `interview_audio.py` | Alto (zona congelada, API de pago) | Este spec + verify + cto-review antes del deploy |
| Parámetros nuevos para Deepgram (`diarize`) | Medio (costo) | cto-review con el precio verificado |
| Prompt de sugerencia nuevo (afecta también al modo texto) | Medio | E2E + evaluación manual de 10 casos |
| Deploy | Alto (producción) | Firma de Jonathan |

## Release, rollback y evidencia

- **Release:** cto-review → deploy de Jonathan → una prueba con su teléfono
  en altavoz, como la de humo del 13 oct, con calibración.
- **Rollback:** `heroku rollback -a career-ai`. No hay datos persistentes.
- **Evidencia:**
  - pytest (eventos reales y fixture sintético de dos voces);
  - Vitest;
  - E2E en Chromium;
  - reporte local de evaluación con la grabación del 13 oct (solo métricas
    agregadas, en el dictamen del verify).

## Métricas de resultado

| Métrica | Fuente | Baseline (13 oct) | Review | Decisión |
|---|---|---|---|---|
| % de tarjetas que son preguntas reales del entrevistador | Resumen de sesión + revisión del video | 33 % (1 de 3) | Tras 3 llamadas reales | ≥ 80 %: continuar · si no, revisar la separación |
| % de ruido en la barra (respaldo) | Resumen de sesión | 74 % (29 de 39) | Tras 3 llamadas | < 20 %: continuar |
| Fin de pregunta → primera palabra de la pista (p50 / p90) | Resumen de sesión | 1.0 s / 1.4 s | Tras 3 llamadas | p50 ≤ 0.5 s y p90 ≤ 1.5 s |

El resumen de sesión suma los conteos de etiquetas y de generaciones
anticipadas; es una tarea del plan.

## Archivos afectados (estimación, no contrato)

- **Backend:**
  - `app/services/turn_detector.py` (etiqueta de voz, muletillas);
  - `app/services/live_session.py` (cálculo de banda y calibración);
  - `app/services/stt_stream.py` (`diarize` y log de keyterms, si gana el
    CS-0);
  - `app/api/interview_audio.py` (mensaje de calibración);
  - `app/services/llm_client.py` (perspectiva, pista + detalle);
  - `app/api/interview.py` (evento SSE de la pista);
  - tests y un fixture sintético de dos voces.
- **Frontend:**
  - `components/LiveInterview.tsx` (calibración, tarjeta fija, estilo de
    turnos del candidato);
  - `lib/cardPolicy.ts`, `lib/liveTranscript.ts` y `api/client.ts`;
  - `hooks/useLiveAudio.ts`.
- **E2E:** `e2e/` (dos voces, tarjeta fija).
- **Docs:** el spec C2-SPEC-01 se marca como reemplazado en REQ-04 y REQ-07
  por este spec; `HANDOFF.md` y `STATE.md`.
- **Coordinación con C3-SPEC-01:** los archivos compartidos son
  `client.ts`, `App.tsx`, `config.py`, `main.py`, `ci.yml`, `HANDOFF.md` y
  `STATE.md`. Cada PR se rebasa sobre `main` antes del verify, y quien llegue
  segundo resuelve el conflicto.

## Definition of Done

- [ ] El CS-0 tiene un dictamen escrito: método de separación elegido con
      sus números y keyterms medidas.
- [ ] AC-01 a AC-08 cubiertos, con la CI en verde, incluido el E2E de modo
      pestaña sin cambios.
- [ ] La evaluación local con la grabación del 13 oct cumple AC-01 y AC-07,
      y solo sus métricas aparecen en el dictamen.
- [ ] cto-review emitido y firmado antes del deploy.
- [ ] Prueba real de Jonathan con el teléfono en altavoz después del deploy.
- [ ] `HANDOFF.md` y `STATE.md` actualizados.
