# Spec: careerai-mcp

spec_id: LB03-SPEC-01
Origen: Learning Backlog LB-03 (HANDOFF §6) · Lane: Standard (paquete nuevo,
sin cambios en la app en producción)
Estado: **PENDIENTE DE APROBACIÓN**
Skills aplicadas: `design-spec` + `system-design-spec` (reglas 3, 6, 9, 10)

---

## Resumen general

Un servidor MCP local (`careerai-mcp`) que permite usar CareerAI desde
Claude: Claude Code o Claude Desktop. El servidor no tiene lógica de negocio
propia. Es un cliente delgado de la API pública que ya corre en producción
(`/api/cv/generate` y `/api/interview/text`) y del perfil verificable del
usuario, guardado en un archivo JSON local.

Por qué ahora (decisión de CEO delegada por Jonathan, 30 sep 2026):
- Abre un canal de producto: quien ya trabaja en Claude usa CareerAI sin
  salir de su conversación.
- Prepara el Ciclo #3: el perfil verificable entra como archivo y el servidor
  lo pasa tal cual, sin reescribirlo.
- Vuelve verificable una línea del CV de Jonathan ("construí un servidor
  MCP") en un nicho donde ya hay una vacante activa (Bull Rocket, 30 sep).
  [evidencia: la vacante pide MCP; su perfil solo muestra uso de conectores]

## Objetivos del usuario

1. Como candidato que trabaja en Claude, quiero pedir "hazme el CV para esta
   vacante" y recibir el score, las palabras faltantes y el PDF, sin abrir la
   web.
2. Como candidato, quiero practicar una respuesta de entrevista desde Claude,
   anclada a mi perfil verificable, con la misma regla anti-invención del
   copiloto.

## Alcance estricto v1

### Incluye

- Paquete Python `mcp/` en el repo, con transporte stdio y la SDK oficial
  `mcp` 2.x (`MCPServer`).
- Tres herramientas:
  - `generate_cv(job_posting)`: lee el perfil del archivo configurado, llama
    a `POST /api/cv/generate` y devuelve el puesto, el score, Matched,
    Missing y la URL absoluta del PDF.
  - `interview_suggestion(question)`: arma el contexto con el perfil, llama
    a `POST /api/interview/text`, consume el SSE y devuelve el texto
    completo con su intención e idioma. Un evento `error` se devuelve como
    error de la herramienta.
  - `get_profile()`: devuelve el perfil verificable tal como está en el
    archivo.
- Configuración solo por variables de entorno: `CAREERAI_API_URL` (por
  defecto, la URL de producción) y `CAREERAI_PROFILE` (ruta al JSON del
  perfil).
- `profile.example.json` con datos ficticios y una guía de instalación para
  Claude Code (`claude mcp add`) y Claude Desktop.
- Job de CI propio (pytest con HTTP simulado).

### NO incluye

- Servidor MCP remoto, OAuth, multiusuario y publicación en directorios de
  conectores (llegan con Phase 3).
- Cambios en la API o en el frontend de CareerAI.
- Llamadas directas a la API de Anthropic o a otro LLM desde el servidor.
- Guardar el perfil fuera del archivo local del usuario.

## Requisitos

- **REQ-01 · Cliente delgado.** Toda la lógica (score, PDF y sugerencia)
  vive en la API existente. El servidor solo traduce entre MCP y HTTP.
- **REQ-02 · El perfil es la única fuente de hechos.** Se envía sin
  modificar. Las instrucciones del servidor le dicen a Claude que no agregue
  experiencia y que trate Missing como huecos, no como afirmaciones.
- **REQ-03 · Contrato.** Los cuerpos que envía coinciden con
  `backend/app/schemas/cv.py` e `interview.py`. Un cambio en esos schemas
  obliga a actualizar el servidor y sus tests, igual que `client.ts`
  (CLAUDE.md).
- **REQ-04 · SSE.** Parsea `meta → chunk* → error? → done`. Un `error` se
  convierte en un error de herramienta con el código (`rate_limit`,
  `llm_response`, …).
- **REQ-05 · Instalación en un comando** para Claude Code y una entrada JSON
  para Claude Desktop, documentadas en `mcp/README.md`.
- **NFR-01 · Timeouts (regla 6).** 60 s para `generate_cv` (el CV Engine hace
  varias llamadas a Gemini) y 40 s para `interview_suggestion`. Sin
  reintentos: una sugerencia no es idempotente para el usuario.
- **NFR-02 · Sin secretos.** La API es pública, así que el servidor no
  maneja keys. El perfil vive solo en la máquina del usuario y nunca entra
  al repo.

## Comportamiento esperado

- **Flujo feliz:**
  1. Claude llama a `generate_cv` con la vacante.
  2. El servidor responde con el score, Matched, Missing y la URL del PDF.
  3. Claude presenta los huecos sin rellenarlos.
- **EDGE-01 · `CAREERAI_PROFILE` no existe o no es JSON válido:** error claro
  con la ruta esperada y un enlace al ejemplo.
- **EDGE-02 · La API no responde o devuelve 5xx:** error con el código HTTP.
  El dyno de Heroku puede tardar en despertar.
- **EDGE-03 · El perfil no cumple el schema (422):** devuelve el detalle de
  validación de la API.

## Manejo de errores

Cada fallo es un error de la herramienta con un mensaje accionable. El
servidor no escribe logs con el contenido del perfil.

## Supuestos y decisiones abiertas

- [supuesto] Claude Code y Claude Desktop en macOS 12 ejecutan servidores
  stdio de Python 3.11 (la Mac de Jonathan ya corre Python para el backend).
- [decisión, Claude como CEO por delegación] v0 local, antes del CS-4,
  acotado a un bloque de trabajo. El servidor remoto queda para Phase 3.

## Riesgo por acción

| Acción | Riesgo | Gate |
|---|---|---|
| Agregar el paquete `mcp/` y su job de CI | Bajo (no toca la app) | CI verde + verify |
| Llamadas a la API pública de producción desde la Mac del usuario | Bajo (mismo uso que la web) | H-MCP de Jonathan |

## Release, rollback y evidencia

- **Release:** merge a `main`. No hay deploy, porque se instala localmente
  desde el repo.
- **Rollback:** `claude mcp remove careerai`.
- **Evidencia:**
  - CI con HTTP simulado.
  - H-MCP: Jonathan registra el servidor y obtiene un CV desde Claude Code.

## Métricas de resultado

`outcome_review: not_applicable`. Es dogfood de un solo usuario. Las métricas
de canal llegan con el servidor remoto (Phase 3).

## Archivos afectados (estimación, no contrato)

`mcp/pyproject.toml`, `mcp/careerai_mcp/server.py`, `mcp/tests/`,
`mcp/profile.example.json`, `mcp/README.md`, `.github/workflows/ci.yml`,
`CLAUDE.md` (regla de contrato), `README.md` (enlace).

## Definition of Done

- [ ] **AC-01** — Con HTTP simulado, `generate_cv` envía el perfil del archivo
  sin cambios y devuelve el score, Matched, Missing y la URL absoluta del PDF.
- [ ] **AC-02** — `interview_suggestion` arma el texto completo desde los
  `chunk` y convierte un evento `error` en un error de herramienta.
- [ ] **AC-03** — Perfil ausente, JSON inválido, 422 y 5xx producen errores
  accionables (tests).
- [ ] **AC-04** — El servidor expone las tres herramientas con sus esquemas
  (test con `list_tools()` de la SDK) y el módulo arranca por stdio (prueba de
  humo en CI).
- [ ] **AC-05** — Job de CI `mcp · pytest` en verde.
- [ ] **AC-06** — [HUMANO] H-MCP: desde Claude Code en la Mac de Jonathan,
  `generate_cv` con una vacante real devuelve el score y un PDF que abre.
