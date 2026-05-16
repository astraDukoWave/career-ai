# CareerAI — STATE.md
Sprint activo: Railway Deploy
Día: 4 de 7 — deadline May 19, 2026

## ✅ Funcionando
- CV Engine: ATS score + PDF (smoke test pasado)
- Interview Copilot texto + SSE streaming
- Audio WebSocket + Deepgram Nova-3 STT real
- CORS env-driven resuelto
- README actualizado (sin referencias a mock)

## 🔧 En construcción ahora
- Railway deploy: URL pública estable

## 🚨 Bloqueante único
- Sin Railway URL = sin Application URL para submission en lablab.ai

## 📋 Definition of done este sprint
- [ ] GET https://[railway-url]/health → 200 OK
- [ ] POST https://[railway-url]/api/cv/generate → PDF generado
- [ ] POST https://[railway-url]/api/interview/text → SSE streaming funciona
- [ ] Frontend Railway URL carga sin errores de CORS

## ⏭️ Siguiente acción única
Railway deploy — configurar variables de entorno y primer deploy

## 🔒 STT congelado en v2 (chunked pre-recorded)
Deepgram Live Streaming WebSocket → v3 post-hackathon (BACKLOG)
