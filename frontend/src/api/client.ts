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
