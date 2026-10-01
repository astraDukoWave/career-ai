# STATE.md — Ciclo activo

**Fase:** Ciclo #2, copiloto en tiempo real. Spec C2-SPEC-01 v1.1 y plan
C2-PLAN-01 aprobados.
- Hecho: CS-1 (CI), CS-2 y CS-3 (Context Bridge) y CS-0 (benchmark de STT; se
  queda Nova-3 `multi`).
- Siguiente: CS-4.

**Producción:** Heroku v20, desplegada desde `main` @ `04b8f5d` el 30 sep 2026
(deploy manual de Jonathan).

**Cola inmediata (detalle en HANDOFF.md §6 y §10):**
1. LB-03: servidor MCP de CareerAI. Spec y plan en el PR #15, pendientes de
   aprobación; va antes del CS-4, acotado a un bloque de trabajo.
2. C2: CS-4 → CS-5 → CS-6 → CS-8 → CS-7, después D-2 y el E2E humano
   (H-2, H-3).
3. Experimento del radar de vacantes: tarea programada semanal, los lunes,
   del 30 sep al 26 oct 2026.
4. Ciclo #3: perfil verificable con GitHub como fuente de verdad.

**Bloqueantes:** ninguno.

*Última actualización: 30 sep 2026*
