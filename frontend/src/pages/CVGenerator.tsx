// CVGenerator — the only page in the CV Engine sprint.
//
// Layout (single column, two panels):
//   Left  : job posting textarea + minimal profile form + Generate button
//   Right : CV preview iframe + ATS score panel
//
// Profile inputs are intentionally simple for the MVP:
//   - Name (single field)
//   - Skills (comma-separated)
//   - Experience (one block: title, company, dates, bullets one-per-line)
// More structured forms can come later; today we ship the demo loop.

import { useState } from 'react';
import {
  ApiError,
  CVResponse,
  ExperienceItem,
  generateCV,
  pdfUrl,
} from '../api/client';
import CVPreview from '../components/CVPreview';

interface FormState {
  name: string;
  email: string;
  location: string;
  skillsCsv: string;
  expTitle: string;
  expCompany: string;
  expStart: string;
  expEnd: string;
  expBulletsRaw: string;
}

const EMPTY_FORM: FormState = {
  name: '',
  email: '',
  location: '',
  skillsCsv: '',
  expTitle: '',
  expCompany: '',
  expStart: '',
  expEnd: 'Present',
  expBulletsRaw: '',
};

function buildExperience(form: FormState): ExperienceItem[] {
  if (!form.expTitle.trim() && !form.expCompany.trim()) return [];
  const bullets = form.expBulletsRaw
    .split('\n')
    .map((b) => b.trim())
    .filter(Boolean);
  return [
    {
      title: form.expTitle.trim(),
      company: form.expCompany.trim(),
      start_date: form.expStart.trim(),
      end_date: form.expEnd.trim() || 'Present',
      bullets,
    },
  ];
}

function ScoreBadge({ score }: { score: number }) {
  const pct = Math.round(score * 100);
  const tone = score >= 0.6 ? '#1f8b4c' : score >= 0.4 ? '#c08400' : '#b3261e';
  return (
    <div
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 8,
        padding: '6px 12px',
        borderRadius: 999,
        background: '#fff',
        border: `1px solid ${tone}`,
        color: tone,
        fontWeight: 600,
        fontSize: 14,
      }}
    >
      ATS score: {pct}%
    </div>
  );
}

function KeywordChips({
  title,
  items,
  tone,
}: {
  title: string;
  items: string[];
  tone: 'good' | 'bad';
}) {
  const bg = tone === 'good' ? '#e7f5ec' : '#fdecea';
  const fg = tone === 'good' ? '#1f8b4c' : '#b3261e';
  return (
    <div>
      <div style={{ fontSize: 13, color: '#444', marginBottom: 6 }}>
        {title} ({items.length})
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
        {items.length === 0 ? (
          <span style={{ fontSize: 13, color: '#888' }}>—</span>
        ) : (
          items.map((kw) => (
            <span
              key={kw}
              style={{
                background: bg,
                color: fg,
                padding: '3px 10px',
                borderRadius: 999,
                fontSize: 12,
              }}
            >
              {kw}
            </span>
          ))
        )}
      </div>
    </div>
  );
}

export default function CVGenerator() {
  const [jobPosting, setJobPosting] = useState('');
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [result, setResult] = useState<CVResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const update =
    (key: keyof FormState) =>
    (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
      setForm((prev) => ({ ...prev, [key]: e.target.value }));

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const skills = form.skillsCsv
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean);
      const response = await generateCV({
        job_posting: jobPosting,
        user_profile: {
          name: form.name.trim(),
          email: form.email.trim() || undefined,
          location: form.location.trim() || undefined,
          skills,
          experience: buildExperience(form),
          education: [],
        },
      });
      setResult(response);
    } catch (err) {
      const msg =
        err instanceof ApiError
          ? `${err.status} — ${err.message}`
          : err instanceof Error
            ? err.message
            : 'Unknown error';
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  const canSubmit =
    !loading && jobPosting.trim().length >= 20 && form.name.trim().length > 0;

  return (
    <div
      style={{
        maxWidth: 1280,
        margin: '0 auto',
        padding: 24,
        display: 'grid',
        gridTemplateColumns: '1fr 1fr',
        gap: 24,
      }}
    >
      <header style={{ gridColumn: '1 / -1' }}>
        <h1 style={{ margin: 0, fontSize: 24 }}>CareerAI — CV Engine</h1>
        <p style={{ margin: '4px 0 0', color: '#555' }}>
          Paste a job posting + your profile. We tailor the CV and score it
          against ATS keywords.
        </p>
      </header>

      {/* ---------- LEFT: form ---------- */}
      <form
        onSubmit={onSubmit}
        style={{
          background: '#fff',
          padding: 20,
          borderRadius: 12,
          border: '1px solid #e2e2e8',
          display: 'flex',
          flexDirection: 'column',
          gap: 14,
        }}
      >
        <Field label="Job posting (paste raw text)">
          <textarea
            required
            value={jobPosting}
            onChange={(e) => setJobPosting(e.target.value)}
            placeholder="Paste the full job description here…"
            rows={8}
            style={textareaStyle}
          />
        </Field>

        <Field label="Full name *">
          <input value={form.name} onChange={update('name')} style={inputStyle} required />
        </Field>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <Field label="Email">
            <input value={form.email} onChange={update('email')} style={inputStyle} />
          </Field>
          <Field label="Location">
            <input
              value={form.location}
              onChange={update('location')}
              style={inputStyle}
            />
          </Field>
        </div>

        <Field label="Skills (comma-separated)">
          <input
            value={form.skillsCsv}
            onChange={update('skillsCsv')}
            placeholder="Python, FastAPI, PostgreSQL, Docker, React"
            style={inputStyle}
          />
        </Field>

        <fieldset style={fieldsetStyle}>
          <legend style={{ fontWeight: 600, fontSize: 13, padding: '0 6px' }}>
            Last role
          </legend>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <Field label="Title">
              <input
                value={form.expTitle}
                onChange={update('expTitle')}
                style={inputStyle}
              />
            </Field>
            <Field label="Company">
              <input
                value={form.expCompany}
                onChange={update('expCompany')}
                style={inputStyle}
              />
            </Field>
            <Field label="Start">
              <input
                value={form.expStart}
                onChange={update('expStart')}
                placeholder="2022-01"
                style={inputStyle}
              />
            </Field>
            <Field label="End">
              <input value={form.expEnd} onChange={update('expEnd')} style={inputStyle} />
            </Field>
          </div>
          <Field label="Bullets (one per line)">
            <textarea
              value={form.expBulletsRaw}
              onChange={update('expBulletsRaw')}
              rows={5}
              placeholder={'Built X to reduce Y by 30%\nLed migration from A to B'}
              style={textareaStyle}
            />
          </Field>
        </fieldset>

        <button type="submit" disabled={!canSubmit} style={primaryButton}>
          {loading ? 'Generating…' : 'Generate CV'}
        </button>

        {error && (
          <div
            style={{
              background: '#fdecea',
              color: '#b3261e',
              border: '1px solid #f5c2bd',
              borderRadius: 8,
              padding: 12,
              fontSize: 14,
            }}
          >
            {error}
          </div>
        )}
      </form>

      {/* ---------- RIGHT: preview + score ---------- */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        {result && (
          <div
            style={{
              background: '#fff',
              padding: 16,
              borderRadius: 12,
              border: '1px solid #e2e2e8',
              display: 'flex',
              flexDirection: 'column',
              gap: 12,
            }}
          >
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                gap: 12,
              }}
            >
              <ScoreBadge score={result.ats_score} />
              {result.rewritten && (
                <span style={{ fontSize: 12, color: '#555' }}>
                  Bullets rewritten by LLM to lift score
                </span>
              )}
            </div>
            <KeywordChips
              title="Matched"
              items={result.matched_keywords}
              tone="good"
            />
            <KeywordChips
              title="Missing"
              items={result.missing_keywords}
              tone="bad"
            />
          </div>
        )}

        <CVPreview
          html={result?.cv_html ?? null}
          pdfUrl={result ? pdfUrl(result.cv_pdf_url) : null}
        />
      </div>
    </div>
  );
}

// ---- tiny presentation helpers (kept inline to avoid a styling library) ----

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      <span style={{ fontSize: 13, color: '#444', fontWeight: 500 }}>{label}</span>
      {children}
    </label>
  );
}

const inputStyle: React.CSSProperties = {
  border: '1px solid #d4d4d9',
  borderRadius: 6,
  padding: '8px 10px',
  fontSize: 14,
  background: '#fff',
};

const textareaStyle: React.CSSProperties = {
  ...inputStyle,
  fontFamily: 'inherit',
  resize: 'vertical',
};

const fieldsetStyle: React.CSSProperties = {
  border: '1px solid #e2e2e8',
  borderRadius: 8,
  padding: 12,
  display: 'flex',
  flexDirection: 'column',
  gap: 12,
};

const primaryButton: React.CSSProperties = {
  background: '#111',
  color: '#fff',
  border: 'none',
  borderRadius: 8,
  padding: '12px 16px',
  fontSize: 15,
  fontWeight: 600,
};
