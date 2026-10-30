# STATE.md — Estado por ciclo

Actualizado el 30 oct 2026. Este registro no aprueba specs, planes ni releases.

| Ciclo | Estado | Artefacto | Siguiente |
|---|---|---|---|
| C2 · Copiloto en tiempo real | En producción, enmienda v1.2 | PR #24, `0b10c01`; hallazgos reales en HANDOFF §2 | Conservar operación y trazabilidad; REQ-07-mic sigue `pending-human` |
| C3 · Perfil vivo GitHub | Design-spec, borrador v0.3 pendiente de aprobación | PR #26 · `docs/specs/perfil-vivo-github.md`; consultar head del PR | Revisar correcciones, alcance/estimación y matriz compartida; aprobación antes de design-plan |
| C4 · Llamadas fluidas | Design-spec, borrador v0.3 pendiente de aprobación | PR #27 · `docs/specs/copiloto-llamadas-fluidas.md`; consultar head del PR | Revisar correcciones y experimento C4-EXP-01; aprobación antes de design-plan |

SHARED-01 identifica el PR de contratos, no el experimento de separación. El orden de release y recuperación es una propuesta de los borradores; no se ejecuta todavía.

Reparto de C3/C4: Claude redacta y verifica; Codex implementa tras aprobar spec y plan; Jonathan aprueba y despliega; Claude mergea PR aprobados con SHA fijado. Las skills rc1 siguen en piloto y no sustituyen a las instaladas.

Cola adicional: perfil maestro fuera del repo; skills ci-cd, agent-evals e independent-review; revisar el estado del radar cuyo periodo documentado terminó el 26 oct (no extenderlo automáticamente). LB-06 y LB-07 permanecen en HANDOFF.
