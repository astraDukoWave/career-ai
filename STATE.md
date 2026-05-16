# CareerAI — STATE.md
Sprint activo: Replit Deploy ✅ COMPLETADO
Día: 4 de 7 — deadline May 19, 2026

## ✅ Funcionando
- CV Engine: ATS score + PDF (smoke test pasado)
- Interview Copilot texto + SSE streaming
- Audio WebSocket + Deepgram Nova-3 STT real
- CORS env-driven resuelto
- README actualizado (sin referencias a mock)
- **Deploy en Replit Autoscale — URL pública activa**
- Health endpoint: GET /health → {"status":"ok"} ✅

## 🌐 URLs de producción
- **App**: https://career-ai-astradukowave.replit.app
- **Health**: https://career-ai-astradukowave.replit.app/health
- **CV Engine**: https://career-ai-astradukowave.replit.app/api/cv/generate
- **Interview**: https://career-ai-astradukowave.replit.app/api/interview/text

## 🔧 En construcción ahora
- Smoke test SSE: POST /api/interview/text → streaming 200 OK
- Validar flujo completo CV Engine en producción
- Submission en lablab.ai con URL de Replit

## 📋 Definition of done este sprint
- [x] GET https://career-ai-astradukowave.replit.app/health → 200 OK
- [ ] POST /api/cv/generate → PDF generado
- [ ] POST /api/interview/text → SSE streaming funciona
- [ ] Frontend carga sin errores de CORS

## ⏭️ Siguiente acción única
Submit en lablab.ai con URL: https://career-ai-astradukowave.replit.app

## 🔒 STT congelado en v2
Deepgram Nova-3 prerecorded — no tocar hasta después del hackathon
