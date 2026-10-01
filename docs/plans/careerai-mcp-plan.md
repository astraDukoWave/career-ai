# Plan: careerai-mcp

- **plan_id:** LB03-PLAN-01
- **Spec:** `docs/specs/careerai-mcp.md` (LB03-SPEC-01), en el mismo PR que
  este plan.
- **Rama:** `feat/careerai-mcp` · **Lane:** Standard.
- **Estado: PENDIENTE DE APROBACIÓN.**
- **Orden:** se ejecuta antes del CS-4 de C2-PLAN-01, acotado a un bloque de
  trabajo. Si se pasa, se entrega lo que esté verde y el resto queda como
  deuda registrada.

## Contexto de dominio (con procedencia)

- **D1 · SDK de MCP para Python:** paquete `mcp` 2.2.0 (PyPI).
  - API: `from mcp.server import MCPServer`, `@server.tool()` y
    `server.run(transport="stdio")`. FastMCP se renombró a MCPServer en 2.x.
  - `MCPServer.list_tools()` y `call_tool()` sirven para tests sin
    transporte.
  - *Fuente: instalación e introspección en esta sesión, 30 sep 2026; guía
    de migración v2 de la SDK.*
- **D2 · Registro en los clientes:**
  - Claude Code: `claude mcp add --env K=V --transport stdio <nombre> --
    <comando> [args]`. El `--` es obligatorio. Alcances: `--scope local`
    (por defecto), `user` o `project`.
  - Claude Desktop (macOS): `~/Library/Application
    Support/Claude/claude_desktop_config.json` con `mcpServers.<nombre>` =
    `{command, args, env}`.
  - *Fuente: code.claude.com/docs/en/mcp-quickstart.md y
    modelcontextprotocol.io, consultados el 30 sep 2026.*
- **D3 · Contrato de la API:**
  - `POST /api/cv/generate`: cuerpo `{job_posting, user_profile}`; responde
    `CVResponse` (`ats_score`, `matched_keywords`, `missing_keywords`,
    `job_title`, `cv_pdf_url` relativa).
  - `POST /api/interview/text`: cuerpo `{text, context?}`; responde SSE
    `meta → chunk* → error? → done`.
  - *Fuente: `backend/app/schemas/*` en `main` @ `04b8f5d`.*
- **D4 · Reglas de system design:**
  - Regla 3: stdio entre Claude y el servidor, HTTP hacia CareerAI.
  - Regla 6: timeout en cada llamada, sin reintentos.
  - Regla 9: sin secretos.
  - Regla 10: el servidor es un consumidor más del contrato, igual que
    `client.ts`.

## Cumplimiento de proceso

- Rama nueva antes de tocar archivos; todo entra por PR.
- Checks requeridos: la CI completa más el job nuevo `mcp · pytest`.
- Desviaciones: detener y registrar como `pending-human`.
- Merge: Claude, tras el verify, con merge commit y el SHA fijado.
- No hay deploy: el servidor se instala en la Mac del usuario.

## Change sets

### CS-1 · Servidor, tests, CI y guía

- **Archivos:**
  - `mcp/pyproject.toml` (paquete `careerai-mcp`; dependencias `mcp>=2.2,<3`
    y `httpx`; entry point `careerai-mcp`).
  - `mcp/careerai_mcp/__init__.py`, `server.py` y `__main__.py`.
  - `mcp/tests/test_server.py`.
  - `mcp/profile.example.json` (datos ficticios).
  - `mcp/README.md`.
  - `.github/workflows/ci.yml` (job nuevo).
  - `CLAUDE.md` (regla de contrato) y `README.md` (enlace).
- **Qué hacer:**
  - `server.py`:
    - `MCPServer("careerai", instructions=…)`. Las instrucciones dicen: el
      perfil es la única fuente de hechos; Missing son huecos.
    - Tres herramientas: `generate_cv`, `interview_suggestion` y
      `get_profile`.
    - `load_profile()` lee `CAREERAI_PROFILE` y da errores accionables.
    - El cliente `httpx.AsyncClient` recibe la base desde
      `CAREERAI_API_URL`, con timeouts de 60 s y 40 s.
    - `interview_suggestion` construye el contexto con el perfil: título del
      puesto vacío, resumen, skills y experiencia, respetando los límites del
      schema. Parsea el SSE con la misma lógica de frames que `client.ts`.
    - La URL del PDF se devuelve absoluta.
  - El transporte HTTP se inyecta, para que los tests usen
    `httpx.MockTransport`.
- **Verificación (pytest en CI):**
  - AC-01 a AC-03 con transporte simulado.
  - AC-04 con `list_tools()` más una prueba de humo:
    `python -m careerai_mcp --check` imprime las herramientas y sale con 0.
- **Commit:** `feat(mcp): CareerAI MCP server for Claude Code and Desktop`.

## Tareas [HUMANO]

- **H-MCP · Probar desde Claude Code** (después del merge, ~5 min, en tu
  Mac):
  1. `cd ~/<tu clon>/career-ai && git pull && pip install -e mcp`
  2. Guarda tu perfil verificable como `~/careerai-profile.json`. Te paso
     el JSON listo; no va al repo.
  3. Registra el servidor:
     `claude mcp add --scope user --env CAREERAI_PROFILE=$HOME/careerai-profile.json --transport stdio careerai -- careerai-mcp`
  4. En Claude Code pide: "Usa careerai para generar mi CV para esta
     vacante: …".
  - **Evidencia:** la respuesta con el score y el PDF abierto.

## Orden y dependencias

```
PR del spec y el plan (aprobación) → CS-1 → verify → merge → H-MCP
                                        └→ sigue C2-PLAN-01 CS-4
```

## Tests requeridos

| Qué | Dónde |
|---|---|
| Herramientas con HTTP simulado, errores, SSE y `list_tools()` | `mcp/tests` en CI |
| Prueba de humo por stdio (`--check`) | CI |
| Uso real desde Claude Code | [HUMANO] H-MCP |

## Riesgos → mitigación

- **La API cambia y el servidor queda atrás** → regla de contrato en
  CLAUDE.md y tests que fijan los cuerpos.
- **Arranque en frío del dyno o timeouts** → 60 s para el CV y un mensaje
  que lo explica.
- **El perfil personal se filtra al repo** → `.gitignore` para
  `careerai-profile.json`; solo se versiona el ejemplo ficticio.

---

*Generado: 30 sep 2026 · Pendiente de aprobación.*
