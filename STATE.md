# STATE.md — Ciclo activo

**Fase:** Ciclo #2, copiloto en tiempo real. **En producción desde el 1 oct
2026** (D-2: `ee9fef0`, desplegado por Jonathan; dictamen en
`docs/reviews/c2-d2-cto-review.md`).
- H-2 (pestaña): 3 preguntas detectadas sin clic, latencia p50 0.7 s. Dejó
  un hallazgo: un monólogo se vuelve un solo turno (HANDOFF §2, deuda).
- H-MCP: `careerai-mcp` funciona desde Claude Code. El README corrige el
  orden de `claude mcp add`.

**Cola inmediata (detalle en HANDOFF.md §10):**
1. H-3: prueba humana en Meet con `docs/reviews/h3-guion-meet.md`.
2. Calibración con H-3 y enmienda v1.2 de REQ-04 (necesita el OK de
   Jonathan: zona congelada).
3. Deepgram: confirmar Auto-reload apagado.
4. Radar de vacantes: tarea semanal, los lunes, hasta el 26 oct 2026.
5. Ciclo #3: perfil verificable con login de GitHub.

**Bloqueantes:** ninguno técnico; H-3 es de Jonathan.

*Última actualización: 1 oct 2026*
