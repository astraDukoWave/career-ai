// Context Bridge (C2-SPEC-01 REQ-05): the last generated CV becomes the
// Interview Copilot's only source of facts about the candidate.
//
// Stored in localStorage so it survives a reload and never touches the
// server. Every access is wrapped in try/catch: storage can be missing or
// blocked (private mode, disabled site data) and the copilot must keep
// working without context.

import type { CVRequest, CVResponse, InterviewContext } from '../api/client';

export const CONTEXT_STORAGE_KEY = 'careerai.context.v1';

// Keep the payload inside the backend's hard caps
// (backend/app/schemas/interview.py) so a long CV never triggers a 422.
const MAX_POSTING_CHARS = 4000;
const MAX_LINE_CHARS = 600;
const MAX_SKILL_LINES = 60;
const MAX_BULLETS = 12;
const MAX_ROLES = 6;

export interface StoredContext {
  savedAt: string;
  context: InterviewContext;
}

// Cut by code point, never inside a surrogate pair: a lone half of an emoji
// makes the backend reject the whole request.
function clip(value: string | undefined | null, max: number): string {
  return Array.from((value ?? '').trim()).slice(0, max).join('');
}

const line = (value: string | undefined | null): string => clip(value, MAX_LINE_CHARS);

function firstLine(text: string): string {
  return clip(text.split('\n').find((l) => l.trim()), 300);
}

/** Build the context from what the CV actually printed (falls back to the form). */
export function buildContext(req: CVRequest, res: CVResponse): InterviewContext {
  const profile = res.final_profile ?? req.user_profile;
  return {
    job_title: clip(res.job_title || firstLine(req.job_posting), 300),
    job_posting: clip(req.job_posting, MAX_POSTING_CHARS),
    summary: clip(profile.summary, 4000),
    skills: profile.skills.map(line).filter(Boolean).slice(0, MAX_SKILL_LINES),
    experience: profile.experience.slice(0, MAX_ROLES).map((e) => ({
      title: clip(e.title, 300),
      company: clip(e.company, 300),
      bullets: e.bullets.map(line).filter(Boolean).slice(0, MAX_BULLETS),
    })),
  };
}

export function saveContext(context: InterviewContext): void {
  try {
    const stored: StoredContext = { savedAt: new Date().toISOString(), context };
    window.localStorage.setItem(CONTEXT_STORAGE_KEY, JSON.stringify(stored));
  } catch {
    // Storage unavailable: the copilot simply runs without context.
  }
}

export function clearContext(): void {
  try {
    window.localStorage.removeItem(CONTEXT_STORAGE_KEY);
  } catch {
    // Nothing to clear.
  }
}

function isContext(value: unknown): value is InterviewContext {
  if (!value || typeof value !== 'object') return false;
  const v = value as Record<string, unknown>;
  return (
    typeof v.job_title === 'string' &&
    typeof v.job_posting === 'string' &&
    typeof v.summary === 'string' &&
    Array.isArray(v.skills) &&
    Array.isArray(v.experience)
  );
}

/** The stored context, or null when absent, unreadable or malformed. */
export function loadContext(): StoredContext | null {
  try {
    const raw = window.localStorage.getItem(CONTEXT_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<StoredContext>;
    if (typeof parsed.savedAt !== 'string' || !isContext(parsed.context)) return null;
    return { savedAt: parsed.savedAt, context: parsed.context };
  } catch {
    return null;
  }
}
