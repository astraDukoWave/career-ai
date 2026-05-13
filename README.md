# CareerAI

### AI-Powered ATS Optimizer & Real-Time Interview Copilot

## Why it Matters (El Problema y La Solucion)

Great candidates are still filtered out by rigid ATS rules, then freeze when technical interviews switch context fast. CareerAI solves both pain points: it optimizes job profiles offline for ATS compatibility and delivers real-time structured response guidance (STAR/ELI5) during interviews.

## The Hackathon Scope (Que evaluar hoy)

This MVP includes 2 operational modules for judges to evaluate today:

- **CV Engine**: Analyzes job posts and generates an ATS-optimized PDF resume using WeasyPrint.
- **Interview Copilot**: Detects interviewer intent (code, concept, behavioral) and streams live answer suggestions powered by Gemini 2.5 Flash.

## Demo Rapido (Golden Path)

1. Paste a job vacancy.
2. Review ATS score and generated CV output.
3. Move to Copilot, paste an interview question, and watch live suggestion streaming.

## Stack Tecnologico

- **Backend**: FastAPI, Gemini 2.5, WeasyPrint
- **Frontend**: React, Vite, SSE for streaming, WebSockets

## Quick Start

```bash
cp .env.example .env
docker compose up -d
```

## What's in v2 (Roadmap)

Audio capture currently uses a deterministic mock to stabilize WebSocket behavior in the MVP. The number one priority for v2 is real Speech-to-Text integration with Deepgram.
