// API client — single source of truth for talking to the backend.
// Reads the base URL from an env var (VITE_API_URL) so nothing is hardcoded.

const API_URL = (import.meta.env.VITE_API_URL ?? 'http://localhost:8000').replace(
  /\/+$/,
  '',
);

// Mirrors the Pydantic schemas in backend/app/schemas/cv.py.
// Kept minimal on purpose; expand only when the backend exposes more fields.

export interface ExperienceItem {
  title: string;
  company: string;
  start: string;
  end?: string;
  bullets: string[];
}

export interface EducationItem {
  degree: string;
  institution: string;
  year: string;
}

export interface UserProfile {
  name: string;
  email?: string;
  phone?: string;
  location?: string;
  headline?: string;
  summary?: string;
  linkedin?: string;
  github?: string;
  experience: ExperienceItem[];
  skills: string[];
  education: EducationItem[];
}

export interface CVRequest {
  job_posting: string;
  user_profile: UserProfile;
}

export interface CVResponse {
  cv_html: string;
  cv_pdf_url: string;
  ats_score: number;
  matched_keywords: string[];
  missing_keywords: string[];
  rewritten: boolean;
  // Backend sets this when the final score is below the low-fit threshold
  // (<30%). null/undefined whenever the role is a reasonable match.
  mismatch_warning?: string | null;
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = 'ApiError';
  }
}

export async function generateCV(req: CVRequest): Promise<CVResponse> {
  const res = await fetch(`${API_URL}/api/cv/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });

  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      if (body && typeof body.detail === 'string') detail = body.detail;
    } catch {
      // Response wasn't JSON — fall through with the generic message.
    }
    throw new ApiError(res.status, detail);
  }

  return res.json();
}

// Build an absolute URL for the PDF endpoint so the iframe / download link
// can hit the backend even though it's served on a different port.
export function pdfUrl(relativeUrl: string): string {
  return `${API_URL}${relativeUrl}`;
}

// =============================================================================
// Interview Copilot — POST /api/interview/text streaming helper
// =============================================================================

export type SuggestionIntent = 'tech_code' | 'tech_concept' | 'behavioral_star';
export type SuggestionLanguage = 'en' | 'es';

export interface SuggestionMeta {
  intent: SuggestionIntent;
  language: SuggestionLanguage;
}

export interface SuggestionStreamHandlers {
  onMeta?: (meta: SuggestionMeta) => void;
  onChunk?: (content: string) => void;
  onError?: (code: string, detail: string) => void;
  onDone?: () => void;
}

/**
 * POST `text` to /api/interview/text and consume the SSE stream.
 *
 * `EventSource` is GET-only, so we parse the wire format ourselves from a
 * fetch ReadableStream. SSE frames look like:
 *
 *     event: <type>
 *     data: <json>
 *     <blank line>
 */
export async function streamSuggestion(
  text: string,
  handlers: SuggestionStreamHandlers = {},
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`${API_URL}/api/interview/text`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
    },
    body: JSON.stringify({ text }),
    signal,
  });

  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      if (body && typeof body.detail === 'string') detail = body.detail;
    } catch {
      // Not JSON — keep the generic message.
    }
    throw new ApiError(res.status, detail);
  }

  if (!res.body) {
    throw new ApiError(0, 'Streaming response had no body.');
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let receivedDone = false;

  // Frames are separated by a blank line. Accumulate bytes, split on \n\n,
  // and parse each completed frame as it arrives.
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let sepIdx = buffer.indexOf('\n\n');
    while (sepIdx !== -1) {
      const frame = buffer.slice(0, sepIdx);
      buffer = buffer.slice(sepIdx + 2);

      let event = 'message';
      const dataLines: string[] = [];
      for (const line of frame.split('\n')) {
        if (line.startsWith('event: ')) event = line.slice(7).trim();
        else if (line.startsWith('data: ')) dataLines.push(line.slice(6));
      }

      const rawData = dataLines.join('\n');
      let data: Record<string, unknown> = {};
      if (rawData) {
        try {
          data = JSON.parse(rawData) as Record<string, unknown>;
        } catch {
          // Skip malformed frames rather than aborting the whole stream.
        }
      }

      if (event === 'meta') {
        handlers.onMeta?.(data as unknown as SuggestionMeta);
      } else if (event === 'chunk' && typeof data.content === 'string') {
        handlers.onChunk?.(data.content);
      } else if (event === 'error') {
        const code = typeof data.code === 'string' ? data.code : 'unknown';
        const detail =
          typeof data.detail === 'string' ? data.detail : 'Unknown error';
        handlers.onError?.(code, detail);
      } else if (event === 'done') {
        receivedDone = true;
        handlers.onDone?.();
        return;
      }

      sepIdx = buffer.indexOf('\n\n');
    }
  }

  // Stream closed without an explicit `done` (e.g. the server hung up). Fire
  // onDone so the UI can leave its "streaming" state.
  if (!receivedDone) handlers.onDone?.();
}
