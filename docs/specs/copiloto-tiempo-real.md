# Spec: copiloto-tiempo-real

spec_id: C2-SPEC-01
Ciclo SDD #2 · Lane: High-risk (toca producción y una API de pago)
Estado: **APROBADO** por Jonathan el 29 sep 2026 (contenido de `5b698a0`,
merge `41d62b1`). Congelado: todo cambio posterior entra como enmienda
versionada (v1.1, …).
Skills aplicadas: `design-spec` + `system-design-spec` (reglas 0, 3, 6, 7, 9, 10)

---

## Resumen general

Hoy el Interview Copilot no sirve en una entrevista real. Escucha el micrófono
del candidato y no al entrevistador. Transcribe solo en español y solo cuando
el usuario presiona Stop. Además, desde el commit `24d3ce1` el audio grabado se
pierde: el Stop cierra el WebSocket antes de que el navegador entregue el
archivo. Por último, las sugerencias no conocen el CV ni la vacante, y por eso
inventan historias y métricas.

Este ciclo convierte el copiloto en una herramienta de entrevista en vivo:

- Escucha al entrevistador desde la pestaña de la reunión.
- Transcribe inglés y español en streaming.
- Detecta cuándo termina una pregunta y muestra la sugerencia sin clics.
- Basa la sugerencia **solo** en el CV y la vacante del usuario (Context
  Bridge, antes Phase 1A).

La v1 se diseña para el primer usuario del producto (el fundador, en sus
propias entrevistas) y deja medido lo que hace falta para decidir la
siguiente fase.

Contexto de producto y posicionamiento: ver `strategy.md` (privado, fuera del
repo).

## Objetivos del usuario

1. Como candidato en una entrevista por Meet, Zoom o Teams en Chrome, quiero
   que el copiloto escuche al entrevistador sin que yo haga nada durante la
   pregunta, para concentrarme en responder.
2. Como candidato, quiero que la sugerencia use mis proyectos reales (mi CV) y
   lo que pide la vacante, para no responder algo genérico ni inventado.
3. Como dueño del producto, quiero que cada sesión deje números (preguntas,
   latencia, sugerencias útiles) para medir si el copiloto ayuda.

## Alcance estricto v1

### Incluye

- **Fuentes de audio:**
  - Principal: la pestaña de la reunión, compartiendo en Chrome la pestaña con
    su audio.
  - Respaldo: el micrófono, para un segundo dispositivo junto a las bocinas o
    para una llamada en altavoz.
- **Transcripción en streaming** con Deepgram Nova-3 en modo multilingüe
  (inglés/español), a través del backend. La API key nunca llega al
  navegador.
- **Vocabulario técnico:** hasta 50 términos del CV y de la vacante se envían
  como `keyterm` para que la jerga técnica ("FastAPI", "Zustand", "Kubernetes")
  se transcriba bien.
- **Detección de turnos y preguntas.** Cuando el entrevistador termina de
  hablar, el turno se clasifica como pregunta o no pregunta. Si es pregunta,
  la sugerencia se dispara sola. "Sugerir ahora" queda siempre disponible como
  red de seguridad.
- **Context Bridge.** Al generar un CV, el navegador guarda el perfil y la
  vacante. Cada sugerencia (en vivo o escrita) los envía, y el prompt se ancla
  a esos hechos.
- **Regla anti-invención.** El copiloto nunca inventa empresas, proyectos ni
  métricas. Si no hay una historia del CV que encaje, entrega la estructura de
  la respuesta con marcadores del tipo `[tu ejemplo real: …]`.
- **Pantalla "Modo entrevista":** transcripción en vivo, pregunta detectada,
  sugerencia en streaming, 👍/👎 por sugerencia e indicador de conexión.
  Pensada para una ventana angosta junto a la cámara.
- **Resumen de sesión en el navegador:** preguntas, sugerencias útiles y
  latencia mediana, con un botón "Copiar resumen".
- **Endurecimiento:**
  - Validar `Origin` en el WebSocket (resuelve el TODO de
    `interview_audio.py`).
  - Límite de sesiones simultáneas y de duración.
  - Timeouts en Deepgram y Gemini.
- **CI mínima en GitHub Actions:** tests del backend, build del frontend y una
  prueba de extremo a extremo con audio falso en Chromium.

### NO incluye

- Captura del audio del sistema o app de escritorio. macOS solo lo permite
  desde 14.2, y la máquina objetivo tiene macOS 12.
- Ocultarse al compartir pantalla o evadir plataformas supervisadas. El
  producto no intenta evadir ninguna detección.
- Transcribir la voz del candidato.
- Ayuda dentro de editores de código o assessments.
- Guardar sesiones en el servidor, cuentas, pagos y Practice Mode.
- Safari, Firefox y móvil. Solo Chrome de escritorio, como hoy.

## Calibración de escala (regla 0)

- **Dimensión:** sesiones de entrevista en vivo simultáneas.
- **Valor actual:** 1 `[evidencia: decisión del 28 sep 2026, primer usuario =
  fundador]`.
- **Pico esperado y horizonte:** *decisión abierta*, dueño Jonathan (ver
  Supuestos).
- **Diseño:** para el valor actual, un Basic dyno y hasta 2 sesiones
  simultáneas.
- **Trigger escrito:** si las sesiones simultáneas rechazadas por el límite
  superan 3 en una semana, se revisa el límite y el tamaño del dyno. Antes de
  eso no se agrega nada.

## Requisitos

### Funcionales

- **REQ-01 · Fuente de audio.** El usuario elige "Pestaña de la reunión" o
  "Micrófono".
  - Con pestaña, se pide compartir una pestaña con audio y se descarta la pista
    de video.
  - Si la pestaña llega sin pista de audio, se muestra cómo marcar "Compartir
    audio de la pestaña" y se ofrece reintentar.
- **REQ-02 · Streaming.**
  - El navegador envía audio continuo al backend por WebSocket
    (`/api/interview/ws/live`).
  - El backend abre una conexión en vivo con Deepgram con estos parámetros:
    `model=nova-3`, `language=multi`, `interim_results=true`,
    `utterance_end_ms` ≥ 1000, `endpointing` corto, `smart_format=true` y
    `keyterm` (REQ-03).
  - El backend devuelve al navegador los eventos `partial`, `final` y `turn`.
- **REQ-03 · Keyterms.** Al iniciar la sesión, el navegador manda el
  contexto (REQ-05). El backend deriva hasta 50 términos (skills
  normalizadas y palabras clave de la vacante), sin duplicados, y los usa
  como `keyterm`.
- **REQ-04 · Turnos y preguntas.**
  - Un turno termina con el primer evento que llegue: fin de habla
    (`speech_final`) o `UtteranceEnd`.
  - Un servicio puro (`turn_detector`) marca el turno como pregunta según
    estas señales, en inglés y español: signo de interrogación, palabras
    interrogativas (what/how/why/cuál/cómo/por qué…) e imperativos de
    entrevista (tell me about, describe, walk me through, háblame de,
    cuéntame…).
  - Un turno sin señal de pregunta que dura menos de 2 s y le sigue otro
    dentro de 1.5 s se une al siguiente.
  - Los umbrales son configurables y se calibran en el E2E.
- **REQ-05 · Context Bridge.**
  - Al generar un CV, el navegador guarda en `localStorage` el título de la
    vacante, su texto (máx. 4 000 caracteres), el resumen, las skills
    normalizadas y la experiencia (puesto, empresa, logros).
  - `InterviewTextRequest` acepta un campo `context` opcional (máx. 8 KB;
    truncado determinista).
  - `llm_client` inyecta el contexto en el prompt de sugerencia.
- **REQ-06 · Regla anti-invención.** El prompt exige cuatro cosas:
  - Usar solo hechos del contexto.
  - No inventar empresas, proyectos, cifras ni resultados.
  - Si falta una historia adecuada, entregar la estructura (STAR, explicación
    técnica o enfoque de código) con marcadores `[tu ejemplo real: …]`.
  - Responder en el idioma de la pregunta.
- **REQ-07 · Modo entrevista (UI).**
  - Selector de fuente y botón Iniciar/Detener.
  - Transcripción en vivo: parcial atenuada, final normal.
  - Última pregunta destacada y sugerencia en streaming (contrato SSE
    existente `meta → chunk* → error? → done`).
  - "Sugerir ahora", 👍/👎 por sugerencia y estado de conexión.
  - Aviso "Genera tu CV para respuestas con tus proyectos" si no hay
    contexto.
  - El modo texto actual sigue disponible.
- **REQ-08 · Resumen de sesión.**
  - Al detener, se muestran las preguntas detectadas (automáticas y
    manuales), las sugerencias, las útiles (👍) y la latencia (mediana y p90).
  - "Copiar resumen" deja un texto para pegar en la bitácora del experimento.
  - Nada se guarda en el servidor.
- **REQ-09 · Idioma.**
  - Transcripción: detección automática inglés/español.
  - Sugerencia: en el idioma detectado de la pregunta; `router_agent` ya lo
    resuelve.

### No funcionales

- **NFR-01 · Latencia.**
  - Se mide desde el fin de la pregunta (evento `turn`) hasta el primer
    fragmento de la sugerencia.
  - Objetivo: p50 ≤ 3 s y p90 ≤ 5 s `[supuesto: objetivo a confirmar]`.
  - Presupuesto: cierre de turno 0.3–1.0 s, red y clasificación < 0.3 s,
    primer token del LLM 0.7–1.5 s.
- **NFR-02 · Resiliencia (regla 6).**
  - Timeout de conexión a Deepgram: 5 s.
  - `KeepAlive` a Deepgram cuando no llega audio.
  - Una reconexión automática; si falla, un aviso y el modo texto.
  - Timeout del primer token de Gemini: 10 s; total: 30 s.
  - Sin reintentos automáticos de la sugerencia (no es idempotente para el
    usuario: duplicaría texto).
- **NFR-03 · Router de Heroku.** El audio continuo mantiene tráfico en el
  WebSocket, así que la ventana de 55 s del router no se alcanza con la
  sesión activa. Los pings de uvicorn (20 s) cubren las pausas.
- **NFR-04 · Seguridad (regla 9).**
  - El WebSocket valida `Origin` contra `CORS_ORIGINS` antes de `accept()`.
  - La API key de Deepgram solo existe en el servidor.
  - HTTPS/WSS siempre.
  - Authn/authz siguen fuera hasta Phase 3; el límite de sesiones es la
    protección de costo mientras tanto.
- **NFR-05 · Costo.**
  - Deepgram Nova-3 multilingüe en streaming cuesta aprox. USD 0.0058/min,
    unos USD 0.35 por hora de entrevista `[evidencia: página de precios de
    Deepgram, sep 2026]`.
  - Duración máxima de sesión: 90 min.
  - Máximo 2 sesiones simultáneas por dyno.
- **NFR-06 · CAP (regla 7).** Se elige disponibilidad: si falla el
  streaming, el usuario conserva el modo texto; no hay estado en el servidor
  que proteger.
- **NFR-07 · Compatibilidad.** Chrome de escritorio. La máquina objetivo
  (macOS 12) queda en Chrome 150, que sigue funcionando sin actualizaciones
  desde el 28 jul 2026 `[evidencia]`. Que Chrome 150 en macOS 12 capture el
  audio de una pestaña es un `[supuesto técnico]` que valida el primer E2E
  humano.

## Comportamiento esperado

### Flujo feliz

1. El usuario genera su CV para la vacante en CV Engine; el contexto queda
   guardado en su navegador.
2. Abre "Modo entrevista" en una ventana aparte y ve de dónde viene el
   contexto ("React Developer — de tu último CV").
3. Elige "Pestaña de la reunión", selecciona la pestaña de Meet y marca
   "Compartir audio de la pestaña".
4. El entrevistador habla y aparece la transcripción parcial en vivo.
5. Termina la pregunta: el turno se cierra, se marca como pregunta y la
   sugerencia empieza sola.
6. El usuario responde y marca 👍 o 👎.
7. Al final presiona Detener, ve el resumen de sesión y lo copia a la
   bitácora.

### Casos edge

- **EDGE-01 · Pestaña compartida sin audio.** Aviso con la instrucción y
  botón de reintentar.
- **EDGE-02 · Reunión en app de escritorio (Zoom/Teams).** No hay pestaña.
  Aviso: "Únete desde el navegador" (ambos tienen cliente web) o usa
  Micrófono con altavoz o un segundo dispositivo.
- **EDGE-03 · Pregunta larga con pausas o dos preguntas seguidas.** Aplica
  la regla de unión de REQ-04; "Sugerir ahora" cubre lo que falle.
- **EDGE-04 · Charla casual ("How are you?").** Puede disparar una
  sugerencia breve; es aceptable.
- **EDGE-05 · Deepgram cae o cierra.** Una reconexión; si falla, banner
  "Transcripción no disponible, sigue en modo texto".
- **EDGE-06 · Gemini con 429 o timeout.** Evento `error` en la tarjeta de
  sugerencia (contrato existente `rate_limit` / `internal`); la transcripción
  sigue.
- **EDGE-07 · Sin contexto (no generó CV).** Funciona sin inventar
  (REQ-06) y muestra el aviso de REQ-07.
- **EDGE-08 · El dyno se reinicia a mitad de sesión** (deploy o ciclo
  diario). El WebSocket se cierra, la UI reintenta una vez y el turno en
  curso se pierde.
- **EDGE-09 · Sesión de más de 90 min** o una tercera sesión simultánea.
  Cierre o rechazo con un mensaje claro.
- **EDGE-10 · Origen no permitido.** El WebSocket se cierra con código 1008
  sin llegar a Deepgram.
- **EDGE-11 · Plataforma que restringe herramientas externas.** Fuera del
  control del producto; no se intenta evadir. La bitácora registra si la
  entrevista permitía IA, para separar esos casos al medir.

## Manejo de errores

| Situación | Qué ve el usuario | Qué se registra |
|---|---|---|
| Permiso de pestaña o micrófono denegado | "Chrome no dio acceso al audio" + reintentar | nada (es del cliente) |
| Pestaña sin audio | Instrucción de "Compartir audio de la pestaña" | nada |
| Origen no permitido | (no aplica: no es nuestro frontend) | warning con el origen |
| Deepgram no conecta o se cae | Banner + modo texto | warning con el código de Deepgram |
| Límite de sesiones o de duración | Mensaje con el límite | info |
| Gemini 429 o timeout | Error en la tarjeta de sugerencia | warning (tipo de error) |
| Excepción inesperada | "Algo falló, sigue en modo texto" | traceback |

## Supuestos y decisiones abiertas

- `[supuesto]` **Objetivo de latencia** p50 ≤ 3 s y p90 ≤ 5 s. Dueño:
  Jonathan (se confirma al aprobar).
- `[supuesto]` **La mayoría de las entrevistas se pueden hacer desde Chrome**
  (Meet nativo; Zoom y Teams con cliente web). Dueño: Jonathan; se mide con
  el campo "plataforma" de la bitácora.
- `[hipótesis]` **Turnos + heurística detectan al menos 8 de cada 10
  preguntas sin clic.** Se mide en el E2E con audio de prueba y en sesiones
  reales.
- `[supuesto técnico]` **Chrome 150 en macOS 12 captura el audio de una
  pestaña.** Lo valida el primer E2E humano; si falla, el micrófono con
  altavoz es el camino.
- **Decisión abierta: pico esperado y horizonte de sesiones simultáneas.**
  Dueño: Jonathan. No bloquea la v1.
- **Decisión reabierta por Jonathan (28 sep 2026).** HANDOFF §4 "STT
  pre-grabado" queda reemplazado por streaming. Se registra en HANDOFF al
  cierre del ciclo.
- **Aprobación explícita requerida por CLAUDE.md.** Modificar
  `backend/app/services/stt_client.py` y
  `backend/app/api/interview_audio.py`. Aprobar este spec la otorga.
- `[supuesto]` **La cuenta de Deepgram tiene crédito disponible.** Dueño:
  Jonathan (lo confirma en la consola de Deepgram).

## Riesgo por acción

| Acción propuesta | Clase | Gate que la cubre |
|---|---|---|
| Nuevo WebSocket que reenvía audio a Deepgram (API de pago) | Alto (dinero) | cto-review antes del deploy + límites de NFR-05 |
| Deploy a producción (Heroku) | Alto (producción) | Firma de Jonathan (él ejecuta el push) + rollback |
| Tocar archivos marcados como congelados | Alto (regresión) | Aprobación de este spec + tests de integración |
| Validar `Origin` en el WebSocket | Rutina (reduce riesgo) | PR + test |
| Cambiar el prompt (contexto + anti-invención) | Rutina | PR + tests del prompt |
| Guardar el contexto del CV en `localStorage` | Rutina: datos del propio usuario en su navegador; solo viajan en sus peticiones | PR |
| CI en GitHub Actions (permisos de solo lectura) | Rutina | PR |

## Release, rollback y evidencia

- **Rama y PRs.** Rama `feat/realtime-copilot`; un PR por grupo de change
  sets; CI en verde requerido.
- **Evidencia:**
  - Tests unitarios (turnos, prompt, keyterms).
  - Integración del WebSocket contra un Deepgram falso local.
  - E2E en Chromium con audio falso (archivo WAV con preguntas en inglés y
    español).
  - E2E humano en una reunión real de Meet: una segunda persona o un video
    en otra pestaña hace de entrevistador con el guion de 10 preguntas de
    prueba.
- **Deploy.** Merge a `main` y luego `git push heroku main:main` (lo ejecuta
  Jonathan).
- **Rollback.** `heroku rollback -a career-ai`. El modo texto no depende del
  streaming, así que una falla del modo en vivo no tumba el resto.

## Métricas de resultado

| Métrica | Fuente | Baseline | Review | Decisión |
|---|---|---|---|---|
| Latencia fin de pregunta → primer fragmento (p50/p90) | Resumen de sesión (REQ-08) | n/a (hoy no funciona) | Tras 3 entrevistas reales | Continuar si p90 ≤ 5 s; si no, revisar cierre de turno y modelo |
| Preguntas detectadas sin clic (auto / total) | Resumen de sesión | n/a | Tras 3 entrevistas | Continuar si ≥ 80 %; si no, recalibrar REQ-04 |
| Sugerencias útiles (👍 / preguntas) | Resumen de sesión → bitácora | n/a | Tras 3 entrevistas | Continuar si ≥ 60 %; si no, revisar prompt y contexto |
| Etapas pasadas con copiloto vs. sin él | Bitácora del experimento | Etapas sin copiloto | Tras 5 entrevistas decididas | Continuar, revisar o parar el enfoque en vivo |

La instrumentación de REQ-08 es un change set del plan, no una nota.

## Archivos afectados (estimación, no contrato)

- **Backend:**
  - `api/interview_audio.py`: nuevo endpoint `/ws/live` y validación de
    Origin.
  - `services/stt_client.py`: cliente en vivo.
  - `services/turn_detector.py` (nuevo).
  - `services/llm_client.py`: contexto, anti-invención y timeouts.
  - `schemas/interview.py`: campo `context`.
  - `api/interview.py`: pasa el contexto.
  - `config.py`: parámetros y límites.
  - Tests nuevos.
- **Frontend:**
  - `pages/InterviewCopilot.tsx`: modo entrevista.
  - Un hook nuevo para captura en vivo (pestaña o micrófono).
  - `api/client.ts`: contexto y eventos del WebSocket.
  - `pages/CVGenerator.tsx`: guarda el contexto.
- **CI:** `.github/workflows/ci.yml`.
- **Docs al cierre:** `HANDOFF.md`, `CLAUDE.md` y `STATE.md`.

## Definition of Done

- [ ] **AC-01** — En Chrome, compartir la pestaña de una reunión de Meet
  produce transcripción parcial a menos de 2 s de iniciada el habla (E2E
  humano).
- [ ] **AC-02** — Una pregunta en inglés y otra en español se transcriben
  bien en la misma sesión.
- [ ] **AC-03** — La sugerencia arranca sola en al menos 8 de las 10
  preguntas del guion de prueba.
- [ ] **AC-04** — Latencia en el guion de prueba: p50 ≤ 3 s y p90 ≤ 5 s,
  medida por la instrumentación de REQ-08.
- [ ] **AC-05** — Con CV cargado, la sugerencia a "Tell me about a project
  you're proud of" nombra un proyecto real del CV. Sin CV, no aparece ninguna
  empresa, proyecto ni cifra inventada: test automático sobre el prompt más
  revisión humana de 3 respuestas.
- [ ] **AC-06** — El WebSocket rechaza un `Origin` no permitido (test).
- [ ] **AC-07** — La tercera sesión simultánea se rechaza y una sesión que
  pasa el límite de duración se cierra con aviso (tests con límites
  reducidos).
- [ ] **AC-08** — Con Deepgram caído, la UI muestra el aviso y el modo texto
  sigue funcionando (test con Deepgram falso).
- [ ] **AC-09** — CI en verde en el PR: pytest, build y E2E con audio falso.
- [ ] **AC-10** — El resumen de sesión muestra preguntas, útiles y latencia,
  y "Copiar resumen" funciona.
- [ ] **AC-11** — Los logs de producción de la sesión E2E no tienen
  H12/H15/R14 ni tracebacks.
- [ ] **AC-12** — La API key de Deepgram no aparece en el bundle ni en
  ningún mensaje al navegador (grep).
