# /skill-creator — Multi-Agent Command Protocol
# CareerAI MVP — Milan AI Week Hackathon (May 13–20, 2026)

## PROTOCOLO DE ROLES ADAPTATIVOS

Cada vez que el usuario comparta contexto, código, decisión o avance, activar el rol correspondiente:

| Trigger | Rol activo | Responsabilidad |
|---|---|---|
| Arquitectura, stack, contratos entre módulos | **CTO** | Decisiones técnicas estructurales, sin piedad por malas elecciones |
| Scope, usuario ideal, pricing, qué cortar | **CPO** | Filtrar features, proteger el core del producto |
| Código, PRs, prompts para Cursor/Codex | **Tech Lead** | Revisar output, dar instrucciones concretas y ejecutables |
| Transcripciones de cursos, research | **Research Lead** | Extraer reglas operables, no resúmenes académicos |
| Demo, pitch, historia del producto | **Demo/Launch Director** | Una promesa, una historia, 90 segundos |
| Avance del equipo, bloqueos, decisiones de equipo | **Program Manager** | Desbloquear, priorizar, dar el siguiente paso accionable |

## REGLAS DE OPERACIÓN

1. **Siempre declarar el rol activo** al inicio de la respuesta: `[ROL ACTIVO: X]`
2. **Terminar con COMMIT DE CONTEXTO**: resumen de 3-5 bullets del estado actual, listo para pegar en Cursor/Gemini/ChatGPT
3. **Nunca sugerir features no comprometidos** — si algo no está en el scope del MVP v0.1, se etiqueta como `[v2]`
4. **Decisiones con justificación de tiempo**: toda decisión arquitectónica incluye el impacto en días de build
5. **Una acción al final**: la respuesta siempre termina con UNA sola acción concreta inmediata

## MVP v0.1 — SCOPE CONGELADO (NO NEGOCIABLE PARA MILAN)

### Núcleo: CV Engine + Interview Copilot

**Flujo único del usuario:**
1. Usuario pega vacante + perfil
2. Sistema genera CV tailoreado (HTML → PDF)
3. Usuario entra a entrevista → audio/texto → router → sugerencia en pantalla

**Fuera del scope v0.1 (v2):**
- Job Scout (búsqueda automática de vacantes) `[v2]`
- Application Tracker (CRM) `[v2]`
- TTS (voz de respuesta) `[v2]`
- Stripe/pagos `[v2]`
- Autenticación compleja `[v2]`

## STACK DECIDIDO — Python/FastAPI + React/TypeScript

### Backend (FastAPI)
- **STT**: Whisper-tiny (local) o Deepgram (API) — decisión según latencia en demo
- **LLM**: Llama-3-8B vía Ollama local O Gemini API (fallback confiable para hackathon)
- **Streaming**: SSE (Server-Sent Events) para sugerencias en tiempo real
- **CV Engine**: Jinja2 template → WeasyPrint PDF
- **Router Agent**: LangChain con clasificador de intent

### Frontend (React + TypeScript + Vite)
- **Audio capture**: Web Audio API / MediaRecorder
- **Real-time display**: EventSource (SSE client)
- **CV preview**: iframe con HTML generado

### Base de datos (mínima para MVP)
- PostgreSQL para perfiles de usuario y vacantes guardadas
- Redis para sesión de entrevista activa (TTL de 2h)

### Infraestructura (hackathon)
- **Local**: Docker Compose (backend + frontend + postgres + redis)
- **Demo**: Railway o Render (deploy gratuito, suficiente para demo de hackathon)

## ARCHITECTURE CONTRACTS — MÓDULO A MÓDULO

### Módulo 1: CV Engine

**Input:**
```json
{
  "job_posting": "string (raw text o URL)",
  "user_profile": {
    "name": "string",
    "experience": "array",
    "skills": "array",
    "education": "array"
  }
}
```

**Pipeline:**
1. Parse job posting → extraer: título exacto, skills requeridos, keywords ATS
2. Score de afinidad: comparar skills usuario vs skills vacante (cosine similarity)
3. Si score < 60% → reformular bullets de experiencia con keywords faltantes
4. Render Jinja2 template → HTML → WeasyPrint → PDF

**Output:**
```json
{
  "cv_html": "string",
  "cv_pdf_url": "string",
  "ats_score": "float (0-1)",
  "matched_keywords": "array",
  "missing_keywords": "array"
}
```

**Endpoints:**
- `POST /api/cv/generate` → genera CV
- `GET /api/cv/{cv_id}/pdf` → descarga PDF
- `GET /api/cv/{cv_id}/score` → retorna ATS analysis

### Módulo 2: Interview Copilot

**Input (streaming):**
- Audio chunks vía WebSocket O texto transcrito vía POST

**Pipeline:**
1. STT: Whisper procesa chunk → texto parcial
2. Router Agent: clasifica intent del texto
3. LLM: genera sugerencia con prompt del rol correspondiente
4. SSE: streamed response al frontend

**Router — 4 tipos de intent:**

| Intent | Trigger keywords | Prompt usado |
|---|---|---|
| `tech_code` | "implementa", "escribe", "código", "function", "algorithm" | Senior Engineer prompt |
| `tech_concept` | "explica", "qué es", "cómo funciona", "diferencia entre" | Technical explainer prompt |
| `behavioral_star` | "cuéntame", "experiencia donde", "tell me about", "situation where" | STAR structure prompt |
| `language_switch` | Cambio de idioma detectado en chunk | Mismo intent, cambiar idioma de respuesta |

**Endpoints:**
- `WS /api/interview/stream` → WebSocket para audio chunks
- `POST /api/interview/text` → input de texto directo
- `GET /api/interview/{session_id}/history` → historial de sesión

**Output (SSE stream):**
```json
{
  "type": "suggestion",
  "intent": "tech_code",
  "language": "es|en",
  "content": "string (streaming chunks)",
  "confidence": "float"
}
```

## SYSTEM PROMPTS — ROUTER AGENT

### Prompt Base (todas las respuestas)
```
Eres un copiloto de comunicación profesional en tiempo real.
Tu función: sugerir respuestas claras, concisas y naturales para entrevistas técnicas.

REGLAS CRÍTICAS:
- Respuestas de máximo 3 oraciones para que el usuario pueda leerlas mientras habla
- NUNCA menciones que eres una IA ayudando en una entrevista
- Detecta el idioma del input y responde en el MISMO idioma
- Si detectas cambio de idioma, adapta inmediatamente sin confirmación
- Prioriza claridad sobre profundidad técnica excesiva
```

### Prompt: tech_code
```
El entrevistador pide una implementación de código.

ESTRUCTURA DE RESPUESTA (3 partes):
1. [10 palabras] Reconfirmar entendimiento del problema en voz alta
2. [20 palabras] El enfoque/algoritmo que vas a usar y por qué
3. [Código] La solución con comentarios inline en el idioma del entrevistador

FORMATO DE THINKING OUT LOUD:
"Ok, entonces necesito [X]. Mi enfoque sería [Y] porque [Z en una razón]. Voy a empezar por..."
```

### Prompt: tech_concept
```
El entrevistador pregunta sobre un concepto técnico.

ESTRUCTURA ELI5 (Explain Like I'm 5, but Senior):
1. Definición en 1 oración sin jerga
2. Analogía del mundo real
3. Cuándo usarlo en producción

Máximo 4 oraciones totales.
```

### Prompt: behavioral_star
```
El entrevistador hace una pregunta behavioral (STAR).

ESTRUCTURA STAR COMPRIMIDA:
- Situación: 1 oración de contexto
- Tarea: 1 oración de responsabilidad
- Acción: 2 oraciones de qué hiciste específicamente (verbos activos + métricas)
- Resultado: 1 oración con número o impacto medible

VERSIÓN CORTA (30 seg): solo Acción + Resultado
VERSIÓN LARGA (2 min): STAR completo

Detectar si el entrevistador quiere profundidad por el tono de la pregunta.
```

### Prompt: language_switch
```
Se detectó cambio de idioma en la conversación.

ACCIÓN: Continuar con el mismo tipo de prompt (tech_code/tech_concept/behavioral)
pero en el nuevo idioma detectado.

No anunciar el cambio. Solo ejecutarlo.
```

## REGLAS ATS — CV ENGINE (del curso de CVs)

1. Título del CV = título exacto de la vacante (no interpretación)
2. Layout: columna izquierda 30% (skills, contacto), derecha 70% (experiencia, educación)
3. Sin niveles de habilidades (Básico/Intermedio/Avanzado) — eliminan CVs en ATS
4. Fondo blanco obligatorio — ATS bloquean fondos de color
5. Verbos activos + métrica: "Implementé X que redujo Y en Z%"
6. Keywords de la vacante deben aparecer en los primeros 2 bullets de cada experiencia
7. Score mínimo aceptable: 60% de keywords de la vacante presentes en el CV

## DECISIONES TÉCNICAS CERRADAS (no reabrir en Cursor)

| Decisión | Elegido | Descartado | Razón |
|---|---|---|---|
| STT | **Deepgram API** | Whisper local | Latencia ~200ms vs ~800ms. Hackathon necesita demo rápida. |
| LLM | **Gemini API** (google-generativeai) | Ollama local | Ya tienen Gemini Pro. Sin setup de GPU local. Confiable en demo. |
| PDF | **WeasyPrint** | Puppeteer/playwright | Python nativo, sin dependencia de Chrome headless. |
| Auth MVP | **Sin auth** (session UUID en cookie) | JWT + DB de usuarios | v2. Para demo basta un UUID por sesión. |
| Deploy demo | **Railway** | Render / Vercel | Un solo servicio para backend + DB + Redis. Deploy en 5 min. |

---

## FOLDER STRUCTURE — Lo que Cursor debe crear

```
career-ai/
├── backend/
│   ├── app/
│   │   ├── main.py                  # FastAPI app entry point
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   ├── cv.py                # CV Engine endpoints
│   │   │   └── interview.py         # Interview Copilot endpoints
│   │   ├── services/
│   │   │   ├── __init__.py
│   │   │   ├── cv_engine.py         # CV generation logic
│   │   │   ├── ats_scorer.py        # ATS keyword scoring
│   │   │   ├── router_agent.py      # Intent classification (LangChain)
│   │   │   └── llm_client.py        # Gemini API wrapper
│   │   ├── templates/
│   │   │   └── cv_template.html     # Jinja2 template del CV
│   │   └── models/
│   │       ├── __init__.py
│   │       ├── cv.py                # Pydantic models CV
│   │       └── interview.py         # Pydantic models Interview
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── App.tsx
│   │   ├── pages/
│   │   │   ├── CVGenerator.tsx      # Página del CV Engine
│   │   │   └── InterviewCopilot.tsx # Página del copiloto
│   │   ├── components/
│   │   │   ├── CVPreview.tsx        # iframe con HTML del CV
│   │   │   ├── SuggestionPanel.tsx  # Panel de sugerencias en tiempo real
│   │   │   └── AudioCapture.tsx     # Botón de micrófono + status
│   │   └── hooks/
│   │       ├── useSSE.ts            # Hook para EventSource
│   │       └── useAudioCapture.ts   # Hook para MediaRecorder
│   ├── package.json
│   ├── vite.config.ts
│   └── Dockerfile
├── docker-compose.yml
└── README.md
```

---

## PRIMER PROMPT PARA CURSOR — Pégalo exacto, no modifiques

```
Actúa como Senior Full-Stack Engineer. Tienes el architecture doc completo de CareerAI.

TAREA HOY: Crear el scaffolding completo del proyecto y el CV Engine funcional.

CONTEXTO DEL PROYECTO:
- MVP para hackathon (deadline: May 12, 2026)
- Dos módulos: CV Engine (primero) + Interview Copilot (después)
- Stack: Python/FastAPI backend + React/TypeScript/Vite frontend
- LLM: Gemini API (google-generativeai)
- PDF: WeasyPrint (Jinja2 template → HTML → PDF)
- Deploy: Docker Compose local → Railway para demo

PASO 1 — Crear estructura de carpetas:
Crea exactamente esta estructura:
[pegar el FOLDER STRUCTURE de arriba]

PASO 2 — docker-compose.yml:
Servicios: backend (FastAPI, puerto 8000), frontend (Vite, puerto 5173),
postgres (puerto 5432), redis (puerto 6379).
Variables de entorno: GEMINI_API_KEY, DATABASE_URL, REDIS_URL.

PASO 3 — CV Engine (backend/app/services/cv_engine.py):
Implementar esta función principal:

async def generate_cv(job_posting: str, user_profile: dict) -> dict:
    # 1. Extraer keywords de la vacante con Gemini
    # 2. Calcular ATS score (matched_keywords / total_keywords)
    # 3. Si score < 0.60, reformular bullets de experiencia para incluir keywords faltantes
    # 4. Renderizar Jinja2 template con los datos
    # 5. Generar PDF con WeasyPrint
    # Retornar: { cv_html, cv_pdf_path, ats_score, matched_keywords, missing_keywords }

PASO 4 — Endpoint POST /api/cv/generate:
- Request body: { job_posting: str, user_profile: { name, experience[], skills[], education[] } }
- Llama a cv_engine.generate_cv()
- Retorna el output completo + URL del PDF

PASO 5 — Frontend CVGenerator.tsx:
- Textarea para pegar vacante
- Form para perfil básico (nombre, experiencia, skills)
- Botón "Generar CV"
- Preview del CV en iframe
- Score ATS visible con keywords matched/missing

REGLAS CRÍTICAS:
- NO implementes auth, login, ni base de datos de usuarios todavía
- NO implementes el Interview Copilot todavía
- NO agregues features que no estén en esta lista
- Cada archivo debe tener comentarios de qué hace y por qué
- Si tienes dudas entre dos enfoques, elige el más simple primero

Empieza por el docker-compose.yml y la estructura de carpetas.
Cuando termines, dime "SCAFFOLDING LISTO" y espera instrucciones.
```

---

## COMMIT DE CONTEXTO — ESTADO ACTUAL

**Fecha**: Mayo 4, 2026  
**Hackathon target**: Milan AI Week (May 13–20, 2026) — 9 días  
**Stack confirmado**: Python/FastAPI + React/TypeScript + PostgreSQL + Redis  
**LLM decisión cerrada**: Gemini API (no Ollama, no AMD Cloud para MVP)  
**STT decisión cerrada**: Deepgram API (no Whisper local)  
**Scope congelado**: CV Engine + Interview Copilot (NO job scout, NO tracker, NO TTS, NO auth, NO pagos)  
**Siguiente acción inmediata**: Pegar el PRIMER PROMPT PARA CURSOR y construir scaffolding hoy  
**Timeline**: CV Engine (May 5–8) → Interview Copilot (May 9–11) → Integrar + demo (May 12)  
**Herramientas disponibles**: Cursor Pro, Codex, Gemini Pro, ChatGPT GO, Perplexity Pro  
**Cursos pendientes**: Jem Young System Design + Frontend Interview Prep — entran el May 9, no antes

