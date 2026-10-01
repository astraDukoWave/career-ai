# H-3 · Guion para la prueba humana en Meet

Prueba del modo en vivo (C2-SPEC-01) con una persona real: **AC-04**
(latencia), la métrica de **preguntas detectadas sin clic** y los datos para
calibrar `TURN_CONTINUATION_S` y `STT_ENDPOINTING_MS`. Son unos 25 min.

- **Entrevistador:** la persona que te ayuda. Lee el guion tal cual,
  incluidas las pausas. Debe estar **en otro dispositivo y en otro cuarto**;
  si no, su voz entra también por tu micrófono.
- **Candidato:** Jonathan, en Chrome con CareerAI en una pestaña y Meet en
  otra.

Las preguntas son las mismas del benchmark de voz (`backend/scripts/stt_benchmark.py`)
y de la grabación real de Nova-3 (PR #18): así el resultado se compara con
lo que ya medimos. Se agregan dos casos que salieron de H-2: un monólogo
largo antes de la pregunta (Q11) y comentarios cortos del entrevistador
mientras respondes.

## Antes de empezar (Jonathan)

1. Abre Meet y únete con la otra persona. Usa audífonos.
2. En otra pestaña abre `https://career-ai-95daf7c9a813.herokuapp.com/interview`.
   Antes, genera un CV con tu perfil para que el copiloto tenga contexto.
3. Empieza a grabar la pantalla (QuickTime → Nueva grabación de pantalla).
4. Ten a mano la tabla de anotación del final.

## Ronda 1 · Pestaña de Meet (~15 min)

1. En CareerAI: **Meeting tab → Start listening**. Elige la pestaña de Meet
   y activa **"Also share tab audio"**.
2. Dile a tu ayudante "empezamos".

**Reglas para el entrevistador:**
- Lee cada pregunta a ritmo normal. Donde dice *[pausa]*, cállate el tiempo
  indicado, como si buscaras la palabra.
- Después de cada pregunta, Jonathan responde de 15 a 30 s. Mientras
  responde, di **"ajá"** o **"right"** una o dos veces, en voz baja.
- Espera a que Jonathan diga **"siguiente"** antes de leer la próxima.

| # | El entrevistador dice |
|---|---|
| Q1 | Tell me about a project you're proud of. |
| Q2 | Can you walk me through, *[pausa 1 s]* um, *[pausa 1 s]* how you would design a rate limiter for a public API? |
| B1 | Okay, great. *(no es pregunta: no debe salir tarjeta nueva)* |
| Q3 | What's the difference between useEffect and useLayoutEffect in React? |
| Q4 | So, in your last project, *[pausa 1 s]* how did you handle a production incident with PostgreSQL? |
| Q5 | How would you deploy a FastAPI service to Kubernetes with zero downtime? |
| Q6 | Cuéntame de algún proyecto del que te sientas orgulloso. |
| Q7 | ¿Cómo manejarías, *[pausa 1 s]* este, *[pausa 1 s]* la caché con Redis en una API de alto tráfico? |
| B2 | Perfecto, gracias. *(no es pregunta)* |
| Q8 | ¿Qué ventajas tiene TypeScript sobre JavaScript en un equipo grande? |
| Q9 | Háblame de tu experiencia con GitHub Actions, like how you set up the CI pipeline. |
| Q10 | ¿Por qué quieres trabajar con nosotros? |
| Q11 | *(monólogo, ~40 s, sin pausas largas)* "Te cuento un poco de nosotros: somos un equipo de 12 personas, trabajamos remoto, usamos Python y React, hacemos deploy varias veces al día y cada quien revisa los PRs de otro…" *(sigue improvisando sobre la empresa)* "…entonces, ¿cómo te organizas tú cuando trabajas solo en un proyecto?" |

3. Al terminar: **Stop listening → Copy summary**. Pega el resumen en una
   nota y llena las líneas en blanco (plataforma, notas).

## Ronda 2 · Micrófono (~5 min)

Mide qué pasa cuando tu propia voz también entra a la transcripción.

1. Quítate los audífonos y deja el sonido de Meet por las bocinas.
2. En CareerAI: **Microphone → Start listening**.
3. El entrevistador lee **Q1, Q2, Q7 y Q10** con las mismas reglas.
4. Responde en voz alta como en una entrevista real.
5. **Stop listening → Copy summary**. Pega este segundo resumen debajo del
   primero.

## Tabla de anotación (Jonathan)

Llénala al ver la grabación; no hace falta hacerlo en vivo.

| # | ¿Tarjeta sin clic? (sí / no / usé Suggest now) | La pregunta en la tarjeta: ¿completa, cortada o pegada a otra? | ¿Útil? (👍 / 👎) |
|---|---|---|---|
| Q1 | | | |
| Q2 | | | |
| B1 | (¿salió tarjeta? debería ser "no") | | |
| … | | | |
| Q11 | | ¿La tarjeta mostró todo el monólogo o solo la pregunta? | |

## Qué traer de vuelta

1. Los dos resúmenes copiados, con las líneas en blanco llenas.
2. La tabla de anotación.
3. La grabación de pantalla.
4. El log de esos minutos:
   `heroku logs -a career-ai -n 400 | grep -E "Live (session|WS)|Deepgram|Traceback|H12|H15|R14"`

## Cómo se lee el resultado

- **Detección sin clic** = preguntas con tarjeta sin clic ÷ 11. La meta del
  spec es ≥ 80 %.
- **AC-04:** p50 ≤ 3 s y p90 ≤ 5 s, del resumen.
- **Cortes:** si Q2, Q4 o Q7 aparecen partidas en dos tarjetas, hay que
  subir `TURN_CONTINUATION_S`.
- **Monólogo (Q11):** si la tarjeta muestra todo el monólogo y la
  sugerencia se reinicia varias veces mientras habla, se confirma el
  hallazgo de H-2. Va a la enmienda v1.2 de REQ-04.
- **B1, B2 y los "ajá"** no deben generar tarjetas.
