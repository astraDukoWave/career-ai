# STATE.md — Ciclo activo

**Fase:** Ciclo #2, copiloto en tiempo real. **El código está completo en
`main`** (C2-SPEC-01 v1.1, C2-PLAN-01):
- CS-0 a CS-3: PRs #6 a #12.
- CS-4, streaming en el backend: PR #17.
- CS-5, modo entrevista: PR #19.
- CS-6, resumen de sesión: PR #20.
- CS-8, E2E con audio falso: PR #21.
- CS-7: este PR, con el dictamen D-2 en `docs/reviews/c2-d2-cto-review.md`.

LB-03, el servidor MCP, está mergeado en el PR #16.

**Producción:** Heroku v20 = `04b8f5d` (30 sep 2026). El modo en vivo
**no está desplegado**: espera D-2.

**Cola inmediata (gates humanos; detalle en HANDOFF.md §10):**
1. D-2: confirmar `CORS_ORIGINS` y `DEEPGRAM_API_KEY`, poner una alerta de
   uso en Deepgram y desplegar.
2. H-2: prueba de la pestaña.
3. H-3: E2E humano en Meet, con el resumen copiado y el log.
4. H-MCP: probar `careerai-mcp` desde Claude Code.
5. Experimento del radar de vacantes: tarea semanal, los lunes, hasta el
   26 oct 2026.
6. Ciclo #3: perfil verificable.

**Bloqueantes:** ninguno técnico; los siguientes pasos son de Jonathan.

*Última actualización: 1 oct 2026*
