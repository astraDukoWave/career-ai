# Spec: perfil-vivo-github

spec_id: C3-SPEC-01
Ciclo SDD #3 · Lane: **High-risk**. Toca datos privados (repos privados),
secretos nuevos, una base de datos nueva, el acceso al modo en vivo y
producción.

**Estado:** BORRADOR v0.3, pendiente de aprobación de Jonathan.

**Historial:**
- v0.3 (30 oct 2026): correcciones documentales H1–H10 y propuesta de recuperación conjunta. H11 queda pendiente de estimación; no hay aprobación nueva.
- v0.1 (`caa865d`).
- Auditoría independiente de Codex (17 oct): 7 bloqueos, todos atendidos
  aquí (tabla al final).
- Decisiones de Jonathan del 17 oct: dos specs en paralelo (este y
  C4-SPEC-01); "propone y tú apruebas"; repos públicos y privados; escala de
  un solo usuario; Gemini; acepta el costo de Postgres.
- Decisión de producto delegada a Claude: el orden de las secciones del CV
  (REQ-10).

**Ejecución:** Codex abre un PR por change set; Claude corre `verify`;
Jonathan aprueba y despliega; Claude mergea con merge commit y SHA fijado.

Skills aplicadas: `design-spec` + `system-design-spec` (reglas 0, 2, 3, 5, 6,
7, 8, 9 y 10).

---

## Resumen general

Cada lunes, CareerAI revisa los repos de GitHub de Jonathan que tuvieron
cambios. Los públicos entran por defecto; un privado entra solo si Jonathan lo
habilitó. Propone hasta 3 líneas por repo para el perfil maestro, y cada una
va atada a la evidencia exacta que la respalda: el commit o PR del propio
Jonathan y la frase citada. Jonathan aprueba, edita o rechaza, y lo aprobado
llega al perfil, al CV, al contexto del copiloto y a la exportación para el
MCP.

Precisión: el escaneo usa **una llamada de function calling por repo con
validación en el backend**. No es un agente que elige y encadena
herramientas; eso queda como LB-06.

Además, cumple la decisión del 1 oct (HANDOFF §6): el modo en vivo queda solo
para usuarios con sesión.

## Objetivos del usuario

1. Como desarrollador que busca trabajo, quiero que lo que construí esta
   semana llegue a mi perfil sin redactarlo yo.
2. Como dueño de mi perfil, quiero aprobar cada línea y ver qué la respalda,
   para que mi CV nunca diga algo que no hice ni revele algo confidencial.
3. Como usuario, quiero generar el CV desde mi perfil maestro, y que el
   copiloto conozca mis proyectos.

## Alcance estricto v1

**Incluye:**
- Login con GitHub (solo identidad), allowlist, sesiones del lado del
  servidor y protección CSRF.
- **El modo en vivo (WebSocket) exige sesión.** El modo texto y CV Engine
  siguen abiertos.
- Lectura mínima de GitHub: nunca código, nunca diffs (REQ-03).
- Repos privados con **habilitación por repo** antes de enviar cualquier
  texto a Gemini.
- Perfil maestro en Postgres: importar, ver, editar y exportar a JSON.
- Sección **Proyectos** de punta a punta: perfil, puntaje ATS, CV en HTML y
  PDF, contexto del copiloto (backend, web y MCP) y exportación.
- Escaneo con cola en Postgres, checkpoints por repo y recuperación;
  semanal, más "Escanear ahora".
- Propuestas con afirmación ligada a su evidencia; aprobar, editar o
  rechazar; el rechazo es definitivo.
- "Usar mi perfil maestro" en CV Engine, con el orden de secciones por
  relevancia (REQ-10).

**NO incluye:**
- multiusuario abierto, GitHub App, cuotas o planes (triggers en NFR-04);
- webhooks de GitHub;
- LinkedIn, GitLab o importar PDF;
- un agente que encadene herramientas de consulta (LB-06);
- sincronización automática del MCP: sigue leyendo un JSON local que el
  usuario exporta a mano;
- batch, caching, Redis o workers dedicados;
- cambio de proveedor de LLM (sigue Gemini).

## Requisitos

### Acceso y seguridad

- **REQ-01 · Login, sesiones y CSRF.**
  - OAuth de GitHub sin scopes (solo identidad).
    - El parámetro `state` es aleatorio, de un solo uso, vence en 10 min y
      va ligado a una cookie temporal.
    - Si el `state` falta o no coincide, el login se rechaza.
  - Autorización por `ALLOWED_GITHUB_LOGINS`. Autenticar y autorizar son
    pasos separados.
  - Sesión del lado del servidor:
    - la cookie lleva un id aleatorio de 256 bits (HttpOnly, Secure,
      SameSite=Lax);
    - la base de datos guarda solo su hash, con caducidad de 30 días;
    - en cada login se emite un id nuevo;
    - logout borra la fila, así que **una copia de la cookie deja de servir
      de inmediato**.
  - CSRF: toda mutación de `/api/profile/*` y `/api/auth/logout` exige una
    cabecera con el token CSRF de la sesión (doble envío). Además de
    SameSite.
  - **AC-01:**
    - sin sesión → 401;
    - usuario fuera de la allowlist → 403 sin datos;
    - `state` alterado → rechazo;
    - mutación sin token CSRF → 403;
    - después del logout, la cookie copiada → 401.

    Se prueba con un proveedor OAuth falso.

- **REQ-02 · El modo en vivo exige sesión** (decisión del 1 oct).
  - El WebSocket `/api/interview/ws/live` valida la sesión antes de
    `accept()`, igual que ya valida el Origin. Sin sesión responde HTTP 403
    y no abre Deepgram.
  - Se mantienen el Origin y los límites (2 sesiones, 90 min).
  - Toca `interview_audio.py`, que es zona congelada: este spec y el
    cto-review lo cubren.
  - **AC-02:** un test con uvicorn real comprueba que sin cookie de sesión
    responde 403 y no hay conexión a Deepgram, y que con sesión válida se
    conecta.
  - **Impacto en C4:** su E2E inicia sesión con el OAuth falso. Va en
    "Contratos compartidos".

### Lectura de GitHub (mínimo de datos)

- **REQ-03 · Ni código ni diffs.**
  - **Endpoints permitidos** (allowlist en el cliente; cualquier otro falla
    el test):
    - lista de repos del dueño;
    - metadatos y lenguajes del repo;
    - **lista** de commits: SHA, mensaje, autor, fecha. Nunca el detalle de
      un commit, porque trae `files[].patch`;
    - lista de PRs: número, título, cuerpo, autor y fecha de merge. Nunca
      `/pulls/{n}/files`;
    - README.
  - **Sanitizador obligatorio en las tres fronteras** (persistencia, logs y
    payload al LLM), aplicado a mensajes, cuerpos de PR y README:
    - quita bloques de código (cercados e indentados);
    - quita patrones de secretos (keys, tokens, URLs con credenciales),
      correos y teléfonos;
    - trunca cada texto.
  - Riesgo residual: el token de lectura tiene la *capacidad* de leer código
    aunque la app no la use. Queda registrado y lo acepta Jonathan en el
    cto-review. Mitigación: REQ-04.
  - **AC-03:** los fixtures grabados llevan código y secretos plantados en
    commits, cuerpos de PR y README. El test inspecciona lo que **cruza**
    cada frontera (el payload a Gemini, las filas en la base de datos y los
    logs capturados) y no encuentra ninguno. Otro test falla si el cliente
    llama a un endpoint fuera de la allowlist.

- **REQ-04 · Repos privados con habilitación.**
  - `/profile` lista los repos privados con "Habilitar análisis".
  - Ningún texto de un repo privado se envía a Gemini sin esa habilitación,
    porque aprobar después no deshace un envío.
  - Los públicos entran por defecto, y cualquiera se puede excluir.
  - **AC-04:** un repo privado no habilitado tiene 0 llamadas al LLM; al
    habilitarlo, entra en el siguiente escaneo.

### Escaneo recuperable

- **REQ-05 · Cola en Postgres y checkpoints por repo.**
  - Tablas: `scan_runs` y `repo_cursors`.
    - Un run tiene estado (`queued`, `running`, `done`, `partial`,
      `failed`) y un lease con vencimiento.
    - Cada repo guarda su cursor: último commit y PR procesados, estado,
      intentos y último error.
  - **Worker:** Heroku Scheduler corre `scan_worker` cada 10 min. Reclama
    los runs pendientes con lock (`FOR UPDATE SKIP LOCKED`) y renueva el
    lease mientras trabaja.
  - **Si el proceso muere,** el lease vence y el siguiente tick retoma desde
    los cursores. No hace falta Redis.
  - **Encolado:**
    - el lunes, si no hay un run exitoso esa semana ISO (día configurable
      con `SCAN_WEEKDAY`);
    - "Escanear ahora" encola de inmediato y responde 202 (máx. 3 al día).
      En `/profile` aparece "en cola, listo en ≤ 10 min".
  - **Reintentos:**
    - un repo que falla pasa a `retry` con backoff (máx. 3 intentos en
      ticks posteriores);
    - los demás siguen;
    - el run queda `partial` mientras haya repos pendientes.
  - **Truncamiento visible:**
    - topes de 15 repos por run y 50 commits por repo y por tick;
    - lo que excede queda en el cursor y sigue en el siguiente tick;
    - `/profile` muestra "parcial: faltan N repos o commits".
  - **AC-05:**
    - (a) una falla inyectada tras el repo 1 se reanuda desde el checkpoint
      sin duplicar;
    - (b) un repo con 120 commits se completa en 3 ticks;
    - (c) dos workers simultáneos no procesan el mismo run;
    - (d) la ventana del lunes se cumple aunque el run del lunes falle y se
      complete el martes.

### Propuestas con evidencia

- **REQ-06 · Afirmación ligada a la evidencia.**
  - Gemini recibe la herramienta `propose_profile_lines`. Cada propuesta
    trae:
    - `text`: máx. 160 caracteres, empieza con verbo;
    - `section`: `project` o `experience`;
    - `target`;
    - `claims`: una lista de `{evidence_id, quote}`, donde `quote` es una
      **subcadena exacta** del texto sanitizado de esa evidencia.
  - **Qué cuenta como evidencia:** solo los commits y PRs **cuyo autor es el
    usuario** (su login de GitHub). El README sirve de contexto, pero nunca
    como evidencia.
  - **El backend valida:**
    - la evidencia existe y es del usuario;
    - cada `quote` está literal en *esa* evidencia;
    - toda cifra del `text` aparece en alguna `quote` citada;
    - no hay secretos;
    - la línea no está ya en el perfil.
  - Una propuesta con cifras, tamaño de equipo, liderazgo o métricas de
    impacto se marca **"requiere confirmación explícita"** y se resalta al
    revisarla.
  - **Estados visibles:** `respaldada por <commit/PR>` (la validación pasó)
    → `confirmada por ti` (aprobada). Lo descartado no se muestra; se
    registra con su motivo.
  - **AC-06 (adversarial):**
    - (a) un commit de un colaborador o de un bot dice "lideré un equipo de
      50 personas" → no es evidencia → se descarta;
    - (b) el README dice "500 clientes" → el README no es evidencia → la
      cifra no aparece en ninguna cita → se descarta;
    - (c) un commit del propio usuario dice "lideré un equipo de 50" → se
      permite, marcado "requiere confirmación";
    - (d) hay instrucciones de prompt injection en el README o en un PR → el
      contrato de salida se cumple igual;
    - (e) una `quote` que no está literal → se descarta.

- **REQ-07 · Identidad estable e idempotencia.**
  - La identidad de una propuesta **es su evidencia, no su texto**.
  - La tabla `evidence_claims` tiene una restricción única
    (`user_id`, `repo_id`, `evidence_id`) mientras la propuesta esté en
    `proposed`, `approved` o `rejected`. Una salida nueva del modelo que cite
    evidencia ya reclamada se descarta, aunque esté parafraseada.
  - **El rechazo es definitivo:** esa evidencia no se vuelve a proponer.
    `/profile` permite "volver a considerar" a mano.
  - Aprobar es una transacción con bloqueo de fila. Aprobar dos veces, o en
    paralelo, deja una sola línea.
  - **AC-07:**
    - (a) dos salidas distintas del modelo para la misma evidencia dejan una
      sola propuesta;
    - (b) dos aprobaciones concurrentes dejan una sola línea en el perfil;
    - (c) la evidencia rechazada no reaparece en la semana siguiente.

### Perfil, privacidad y CV

- **REQ-08 · Registro privado contra contenido exportable.**
  - La evidencia (nombre del repo, SHAs, citas) vive en un registro privado
    que solo se ve en `/profile`.
  - Lo que sale de ahí solo lleva el texto aprobado y el **nombre visible**
    del proyecto. Las salidas son:
    - el CV en HTML y en PDF;
    - la exportación JSON;
    - el contexto del copiloto, incluida la copia en `localStorage`.
  - El nombre visible es editable. En los repos privados arranca como
    "Proyecto privado" hasta que el usuario lo nombre. Ninguna salida
    incluye el nombre ni la URL de un repo privado.
  - **AC-08:** con un proyecto privado aprobado, ni el CV (HTML y texto del
    PDF), ni la exportación, ni el contexto contienen su nombre de repo ni
    su URL.

- **REQ-09 · Proyectos de punta a punta.**
  - `UserProfile.projects` (opcional, compatible hacia atrás) se suma a:
    - `_profile_to_text` (puntaje ATS);
    - la plantilla del CV;
    - `InterviewContext` (backend) más `buildContext` en
      `frontend/src/lib/interviewContext.ts`;
    - `build_context` en `mcp/careerai_mcp/server.py`;
    - `client.ts`.
  - **Promesa precisa:** el siguiente CV trae lo aprobado **automáticamente
    en la web** (usa el perfil de la base de datos). En el MCP, solo después
    de exportar y reemplazar `~/careerai-profile.json`.
  - **AC-09 (cadena):** aprobar → perfil → puntaje ATS que cuenta las
    palabras del proyecto → CV en HTML y en texto de PDF (`pdftotext`) con
    la línea → contexto del copiloto con la línea → tests de contrato del MCP
    en verde, con y sin `projects`.

- **REQ-10 · Orden de secciones por relevancia** (decisión de producto del
  17 oct, delegada a Claude).
  - Un reclutador lee de arriba hacia abajo en segundos, así que primero va
    la evidencia más fuerte **para esta vacante**.
  - Experiencia y Proyectos se ordenan según cuántas palabras clave de la
    vacante acierta cada sección (el mismo scorer del ATS). Si empatan, va
    primero Experiencia.
  - Sin experiencia, solo aparece Proyectos. Es el caso de un candidato que
    empieza.
  - CV Engine tiene un selector: automático, Experiencia primero o Proyectos
    primero.
  - **AC-10:**
    - con una vacante cuyas palabras están en un proyecto y no en la
      experiencia, Proyectos va primero;
    - con un empate, va Experiencia;
    - el selector manual manda sobre el automático.

### No funcionales

- **NFR-01 · Secretos.**
  - `GITHUB_READ_TOKEN`, `GITHUB_OAUTH_CLIENT_ID`,
    `GITHUB_OAUTH_CLIENT_SECRET` y `SESSION_SECRET` viven solo en Config
    Vars.
  - Nunca aparecen en logs ni en respuestas, y la CI busca patrones de
    tokens.

- **NFR-02 · Resiliencia (regla 6).**
  - Timeouts: GitHub 10 s, Gemini 30 s.
  - Reintentos con backoff solo en lecturas de GitHub y en errores 429/5xx.
  - Se respetan las cabeceras `X-RateLimit-*`.
  - Un repo que falla no detiene el run.

- **NFR-03 · Costo.**
  - Topes por tick (REQ-05) y un registro de tokens por run.
  - Postgres (~USD 5/mes, aceptado por Jonathan el 17 oct; el precio exacto
    se confirma en el cto-review). El Scheduler cobra segundos de dyno.
  - **Estimación ilustrativa [hipótesis, no cuota aprobada]:** 15 repos con cambios × 1 llamada × (20 000 tokens de entrada + 2 000 de salida) = 300 000 de entrada y 30 000 de salida por escaneo, antes de reintentos. Con precios verificados `P_in`/`P_out` por millón, costo = `0.30 × P_in + 0.03 × P_out`. Cuatro escaneos equivalen a cuatro veces esa cantidad; escaneos manuales y reintentos se suman. El tope de 15 repos por tick no limita el total si quedan repos para ticks posteriores. Registrar consumo real y presupuesto global del escaneo antes de habilitarlo; estos tokens no sustituyen límites de entrada/salida por definir en el plan.

- **NFR-04 · Escala (reglas 0 y 8).**
  - Usuarios activos: 1. Pico esperado: 1 en 3 meses.
  - Triggers medibles:
    - **más de 1 usuario:** GitHub App por usuario, con permisos por repo
      (reemplaza el PAT), y `user_id` en todas las consultas;
    - **más de 20:** cuotas;
    - **más de 100, o un run de más de 10 min:** worker dedicado y la API de
      batch del proveedor;
    - **contexto por encima del mínimo de caching, con más de 1 escaneo al
      día:** caching.

- **NFR-05 · Privacidad.**
  - No se guarda código. Borrar el perfil borra todo (perfil, evidencia,
    runs y cursores).
  - Los logs nunca llevan texto de repos privados.

- **NFR-06 · Sistemas adyacentes.**
  - Si GitHub, Gemini o la base de datos fallan, CV Engine (con el
    formulario) y el modo texto del copiloto siguen funcionando.
  - El modo en vivo requiere la base de datos para validar la sesión. Si
    está caída, responde 503 con un mensaje claro y el modo texto sigue.

### Decisiones de diseño (system-design-spec)

- **Patrón de acceso:** pocas escrituras y pocas lecturas, búsquedas por
  clave → **Postgres** con índices solo en claves.
- **Protocolo:** REST para el perfil y las propuestas.
- **Async (regla 5):** cola en Postgres con lease, en lugar de un broker. Con
  un usuario y ticks de 10 min, alcanza y se recupera de reinicios.
- **Consistencia transaccional:** perfil con transacciones y restricciones únicas;
  el escaneo es reintentable.
- **Authn ≠ authz:** sesión del lado del servidor, no JWT, porque la
  revocación tiene que ser inmediata.
- **Migraciones:** `heroku run`, desde el Loop humano. `heroku.yml` no se
  toca.

## Contratos y orden de release compartidos — propuesta para aprobación

Esta sección debe coincidir en C3 y C4. Separa tres hitos:
- **SHARED-01:** PR de contratos compartidos; se mergea antes del código que los consume.
- **C4-EXP-01:** experimento local para elegir el método de separación; no es el PR de contratos.
- **Release de C3:** entrega la sesión real que necesita C4; un helper falso de tests no acredita esa dependencia en producción.

| Contrato | Dueño | Consumidores |
|---|---|---|
| `UserProfile.projects` e `InterviewContext.projects`, opcionales y compatibles hacia atrás | C3 | Backend, frontend y MCP |
| Sesión exigida en `/api/interview/ws/live`; helper de sesión solo para tests | C3 | Backend y E2E de C4 |
| Campos opcionales WS `speaker`, `confidence`, `revision`, `audio_end_s`; evento SSE `hint` | C4 | Backend, frontend, métricas y consumidor MCP |

SHARED-01 fija nombres, tipos, valores, semántica de ausencia, mensajes que llevan cada campo y orden SSE; añade pruebas de consumidores anteriores y nuevos. No debe habilitar un bypass de autenticación de producción.

**Orden propuesto:** contratos → implementar y verificar C3 y C4 según sus dependencias → desplegar C3 con sesión real → comprobar login, rechazo sin sesión y compatibilidad → desplegar C4. Los experimentos locales de C4 pueden avanzar antes. Cambiar este orden o separar una entrega de autenticación requiere actualizar el spec y conservar el control de acceso.

**Matriz de recuperación:** cada release registra versión Heroku y SHA exactos; no se usa el release anterior implícito como plan de rollback.
- Si falla C4: volver al release probado de C3, que conserva sesión y el esquema compatible. Comprobar rechazo sin sesión, CV y modo texto; detener/reconectar sesiones en vivo según el runbook.
- Si falla C3 antes de salir C4: pausar el worker y el modo en vivo; recuperar el estado o publicar una corrección. El rollback no puede reabrir el modo en vivo sin login.
- Si falla una parte de C3 después de salir C4: tratar la app como un release conjunto. Elegir un SHA compatible con ambos contratos y datos, o pausar las funciones afectadas. No asumir que se puede revertir C3 aisladamente con `heroku rollback`.
- El rollback de código no recupera datos ni deshace servicios externos. La restauración de datos se prueba por separado; no borrar propuestas aprobadas por volver a un release anterior.

**AC-SHARED-01:** prueba de compatibilidad backend/frontend/MCP y del rechazo sin sesión en el release objetivo de rollback. El cto-review identifica esos releases y el dueño del despliegue. Esta propuesta no autoriza desplegar.

## Comportamiento esperado

### Flujo feliz

1. El lunes a las 08:00 se encola el run, y el worker lo toma en ≤ 10 min.
2. Repos con cambios: `inmobot-demo` (público) y `repo-privado-A` (privado,
   habilitado).
3. Se leen listas de commits y PRs, sin diffs; se sanitiza; se filtra el
   ruido.
4. Hay una llamada a Gemini por repo. El backend valida citas, autoría y
   cifras.
5. En `/profile` aparecen 5 propuestas, cada una con "respaldada por …". Una
   viene marcada "requiere confirmación".
6. Jonathan aprueba cuatro y rechaza una. El proyecto privado lo nombra
   "Proyecto A".
7. Genera un CV con su perfil maestro. Como la vacante acierta más con
   Proyectos, esa sección va primero.

### Casos edge

- **EDGE-01 · Sin cambios:** el run termina en `done`, sin llamadas al LLM.
- **EDGE-02 · Token vencido o revocado:** el run queda `failed` con "requiere
  token nuevo" y el aviso aparece en `/profile`.
- **EDGE-03 · Repo nuevo:** crea un proyecto. Si es privado, se llama
  "Proyecto privado" hasta que lo nombres.
- **EDGE-04 · Repo borrado o renombrado:** las líneas aprobadas se
  conservan, y las propuestas pendientes de ese repo pasan a "obsoletas".
- **EDGE-05 · Prompt injection:** la barrera son la validación (AC-06) y la
  aprobación.
- **EDGE-06 · Datos de un cliente en un repo privado:** las barreras son la
  habilitación por repo, el sanitizador, la prohibición en el prompt y la
  aprobación. Lo que ya se envió no se puede deshacer, y por eso existe la
  habilitación.
- **EDGE-07 · Dos workers a la vez:** el lock y el lease impiden el doble
  proceso (AC-05c).
- **EDGE-08 · Gemini responde 429:** el repo pasa a `retry`.
- **EDGE-09 · Base de datos caída:**
  - `/profile` y el modo en vivo responden 503 con un mensaje claro;
  - CV Engine y el modo texto siguen funcionando.

## Manejo de errores

- **El usuario ve** en `/profile`:
  - el estado del run (en cola, en curso, parcial, con error);
  - los repos pendientes;
  - el aviso de token;
  - el motivo genérico de un error. No ve los detalles internos.
- **Se registra:**
  - el run y el cursor por repo;
  - los conteos de propuestas generadas, descartadas (por motivo),
    aprobadas y rechazadas;
  - los tokens.

  Nunca se registra texto de repos privados ni secretos.

## Supuestos y decisiones abiertas

- [supuesto] Un fine-grained PAT de solo lectura (Metadata, Contents y Pull
  requests) puede listar commits y PRs de los repos privados. Los permisos
  exactos y la caducidad se verifican en el CS-1 contra la documentación de
  GitHub. Verifica Claude; crea el token Jonathan.
- [supuesto] `gemini-3.1-flash-lite` acepta function calling con el SDK
  fijado. Se verifica en el CS-1.
- [supuesto] Con una key de pago, Gemini no usa los datos para entrenar. Se
  verifica **antes** de habilitar cualquier repo privado.
- [hipótesis] Se aprueba al menos el 50 % de las propuestas [base: radar de
  la semana 1, 3 de 3].
- [evidencia] El código actual no lleva proyectos al contexto:
  `InterviewContext` solo tiene `summary`, `skills` y `experience`
  (`backend/app/schemas/interview.py:27`); `build_context` del MCP y
  `_profile_to_text` tampoco [verified-this-session].
- **Inconsistencia que se corrige:** HANDOFF §4 dice "sin auth hasta Phase
  3". El SHARED-01 la alinea con la decisión del 1 oct.

## Riesgo por acción

| Acción | Clase | Gate |
|---|---|---|
| Postgres + Scheduler (costo mensual) | Alto (dinero) | Aceptado por Jonathan el 17 oct; precio exacto en el cto-review |
| Config Vars nuevas (token, OAuth, `SESSION_SECRET`, allowlist) | Alto (secretos) | Las pone Jonathan |
| Exigir sesión al modo en vivo (`interview_audio.py`, zona congelada) | Alto | Este spec + cto-review |
| Enviar textos de un repo privado habilitado a Gemini | Alto (datos) | Términos verificados + riesgo residual aceptado en el cto-review |
| Migraciones | Medio | verify + CI con Postgres efímero |
| `projects` en los schemas (contrato con `client.ts` y el MCP) | Medio | SHARED-01 de contratos + CI `mcp · pytest` |
| Deploy | Alto | Firma de Jonathan |

## Release, rollback y evidencia

- **Release:**
  1. cto-review.
  2. Jonathan crea Postgres, el Scheduler (worker cada 10 min) y las Config
     Vars.
  3. Despliega y corre la migración.
  4. Importa su JSON v4 y habilita los repos privados que elija.
  5. Presiona "Escanear ahora".
- **Rollback:** aplicar la matriz compartida de releases y comprobar la sesión; nunca reabrir el modo en vivo como consecuencia implícita de volver atrás.
- **Respaldo y restauración:** antes de cada migración de producción, generar y verificar un respaldo completo de la base, fuera del filesystem efímero del dyno y con acceso restringido. Incluir perfil, evidencia, propuestas/decisiones y cursores; el JSON exportable del CV por sí solo no recupera ese estado. No versionar datos privados ni credenciales. Definir frecuencia, retención, RPO/RTO y costo antes del release; usar las capacidades verificadas del plan o un procedimiento alternativo aprobado. Restaurar en una base de prueba y comprobar integridad, propuestas aprobadas/rechazadas y recuperación sin duplicados. Las sesiones se invalidan tras la restauración. Conservar evidencia de la prueba sin datos privados.
- **Evidencia:** pytest con fixtures grabadas (sin red) y un LLM falso, los
  tests AC-01 a AC-10, la CI con Postgres efímero y el primer run real.

## Métricas de resultado

| Métrica | Fuente | Baseline | Review | Decisión |
|---|---|---|---|---|
| % de propuestas aprobadas (con o sin edición) | `evidence_claims` | Radar: 3 de 3, a mano | Tras 4 lunes (~16 nov) | ≥ 50 %: continuar · 20–50 %: revisar prompt y filtro · < 20 %: parar |
| % descartadas por la validación, por motivo | Registro del run | n/a | Tras 4 lunes | > 30 %: revisar el prompt |
| % de propuestas "requiere confirmación" rechazadas | `evidence_claims` | n/a | Tras 4 lunes | Si pasa del 50 %, endurecer el prompt |
| Minutos por semana en el perfil | Autorreporte | ~30 min [supuesto] | Tras 4 lunes | Menos de 10: continuar |

## Archivos afectados (estimación, no contrato)

- **Backend:**
  - `app/db.py` y `alembic/`;
  - `app/services/`: `github_reader.py` (con allowlist de endpoints),
    `sanitize.py`, `profile_scanner.py`, `profile_store.py`,
    `sessions.py` y `github_auth.py`;
  - `app/api/`: `profile.py` y `auth.py`;
  - `app/jobs/scan_worker.py`;
  - `app/schemas/`: `profile.py`, `cv.py` (`projects`) e `interview.py`
    (`projects` en el contexto);
  - `app/services/cv_engine.py` (`_profile_to_text` y el orden de
    secciones);
  - `app/templates/cv_template.html`;
  - `app/api/interview_audio.py` (sesión exigida; zona congelada);
  - `app/config.py`, `app/main.py` y `requirements.txt`.
- **Frontend:** `pages/Profile.tsx`, `App.tsx`, `api/client.ts`,
  `lib/interviewContext.ts` y CV Engine (botón y selector de orden).
- **MCP:** `careerai_mcp/server.py` (`projects` en `build_context`) y sus
  tests.
- **CI:** Postgres en `ci.yml`.
- **Docs:** `HANDOFF.md` (§4, §6 y LB-06/LB-07), `STATE.md`, `CLAUDE.md` y
  `AGENTS.md` (convenciones para Codex).

## Tamaño de entrega y pendientes antes de aprobación

H11 requiere una estimación de esfuerzo y capacidad disponible; contar componentes o no encontrar la palabra «sprint» no demuestra que el alcance exceda un sprint. Preparar esa estimación y sus dependencias. Si no cabe, presentar una división concreta para decisión de Jonathan, conservando trazabilidad de todos los requisitos. No considerar aprobada una división C3a/C3b ni eliminar alcance para cumplir el calendario.

Pendientes: aprobación de este borrador y del orden de recuperación propuesto; verificación de los supuestos externos ya enumerados antes de los pasos que dependan de ellos. Se conservan las decisiones previas de costo aproximado de Postgres y aprobación por línea. Esta revisión no instala skills ni autoriza llamadas pagadas.

## Definition of Done

- [ ] El SHARED-01 de contratos compartidos está mergeado antes que cualquier
      otro PR de C3 o C4.
- [ ] AC-01 a AC-10 cubiertos, con la CI en verde (Postgres efímero y
      migraciones desde cero).
- [ ] Las tres fronteras (LLM, base de datos y logs) se prueban sin código
      ni secretos (AC-03).
- [ ] Supuestos de GitHub y Gemini verificados en el cto-review, y el riesgo
      residual del token aceptado por Jonathan.
- [ ] Respaldo y restauración completa probados; RPO/RTO, retención y costos documentados.
- [ ] AC-SHARED-01 y matriz de recuperación verificados.
- [ ] cto-review del deploy firmado.
- [ ] Primer run real, con al menos una propuesta revisada.
- [ ] `HANDOFF.md`, `STATE.md` y `CLAUDE.md` actualizados, y `AGENTS.md`
      creado.

## Auditoría de Codex (17 oct) → cómo se atiende

| # | Hallazgo | Dónde se atiende |
|---|---|---|
| 1 | El alcance de la auth contradice la decisión del 1 oct | REQ-02: el modo en vivo exige sesión; impacto en C4 en los contratos compartidos |
| 2 | AC-03 no prueba que no llegue código | REQ-03: allowlist de endpoints sin diffs, sanitizador y test en las 3 fronteras; riesgo residual del token |
| 3 | Idempotencia por hash del texto | REQ-07: identidad = evidencia, restricción única, rechazo definitivo y transacciones |
| 4 | Recuperación incompleta | REQ-05: cola en Postgres, lease, cursores por repo, reintentos, truncamiento visible y worker cada 10 min |
| 5 | La validación no garantiza veracidad | REQ-06: cita literal por afirmación, autoría del usuario, el README no es evidencia, marca "requiere confirmación" y AC-06 adversarial |
| 6 | Proyectos sin cerrar de punta a punta | REQ-09 + AC-09 en cadena; la promesa del MCP se precisa |
| 7 | Sesión y privacidad | REQ-01 (state, CSRF, revocación), REQ-04 (habilitación por repo), REQ-08 (registro privado contra exportable) |
| + | No es un agente | Resumen y NO incluye (LB-06) |
| + | Specs paralelos contra implementación paralela | Sección "Contratos compartidos" (SHARED-01 primero) |

