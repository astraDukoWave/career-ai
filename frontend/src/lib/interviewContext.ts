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
const MAX_SKILL_LINES = 150;
const MAX_BULLETS = 20;
const MAX_ROLES = 6;

export interface StoredContext {
  savedAt: string;
  context: InterviewContext;
}

const line = (value: string | undefined | null): string =>
  (value ?? '').trim().slice(0, MAX_LINE_CHARS);

function firstLine(text: string): string {
  return (text.split('\n').find((l) => l.trim()) ?? '').trim().slice(0, 300);
}

/** Build the context from what the CV actually printed (falls back to the form). */
export function buildContext(req: CVRequest, res: CVResponse): InterviewContext {
  const profile = res.final_profile ?? req.user_profile;
  return {
    job_title: (res.job_title || firstLine(req.job_posting)).slice(0, 300),
    job_posting: req.job_posting.trim().slice(0, MAX_POSTING_CHARS),
    summary: (profile.summary ?? '').trim().slice(0, 4000),
    skills: profile.skills.map(line).filter(Boolean).slice(0, MAX_SKILL_LINES),
    experience: profile.experience.slice(0, MAX_ROLES).map((e) => ({
      title: line(e.title).slice(0, 300),
      company: line(e.company).slice(0, 300),
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
