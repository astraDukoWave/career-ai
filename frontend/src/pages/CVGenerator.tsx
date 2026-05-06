// CVGenerator — the only page in the CV Engine sprint.
//
// Layout (single column, two panels):
//   Left  : job posting textarea + profile form + Generate button
//   Right : CV preview iframe + ATS score panel
//
// Profile inputs:
//   - Name, email, location
//   - Summary, LinkedIn, GitHub
//   - Skills (comma-separated)
//   - Up to 3 experience entries (title, company, start, end, bullets)
//   - Up to 2 education entries (institution, degree, year)

import { useRef, useState } from 'react';
import {
  ApiError,
  CVResponse,
  EducationItem,
  ExperienceItem,
  generateCV,
  pdfUrl,
} from '../api/client';
import CVPreview from '../components/CVPreview';

interface ExperienceFormItem {
  title: string;
  company: string;
  start: string;
  end: string;
  bulletsRaw: string;
}

interface EducationFormItem {
  institution: string;
  degree: string;
  year: string;
}

interface FormState {
  name: string;
  email: string;
  location: string;
  summary: string;
  linkedin: string;
  github: string;
  skillsCsv: string;
  experience: ExperienceFormItem[];
  education: EducationFormItem[];
}

const MAX_EXPERIENCE = 3;
const MAX_EDUCATION = 2;

const EMPTY_EXPERIENCE: ExperienceFormItem = {
  title: '',
  company: '',
  start: '',
  end: 'Present',
  bulletsRaw: '',
};

const EMPTY_EDUCATION: EducationFormItem = {
  institution: '',
  degree: '',
  year: '',
};

const EMPTY_FORM: FormState = {
  name: '',
  email: '',
  location: '',
  summary: '',
  linkedin: '',
  github: '',
  skillsCsv: '',
  experience: [{ ...EMPTY_EXPERIENCE }],
  education: [],
};

// Top-level form keys whose value is a string (everything except the arrays).
type ScalarFormKey = keyof Omit<FormState, 'experience' | 'education'>;

function buildExperiencePayload(form: FormState): ExperienceItem[] {
  return form.experience
    .map<ExperienceItem>((e) => ({
      title: e.title.trim(),
      company: e.company.trim(),
      start: e.start.trim(),
      end: e.end.trim() || 'Present',
      bullets: e.bulletsRaw
        .split('\n')
        .map((b) => b.trim())
        .filter(Boolean),
    }))
    .filter((e) => e.title || e.company);
}

function buildEducationPayload(form: FormState): EducationItem[] {
  return form.education
    .map<EducationItem>((e) => ({
      institution: e.institution.trim(),
      degree: e.degree.trim(),
      year: e.year.trim(),
    }))
    .filter((e) => e.institution || e.degree);
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

function MismatchBanner({
  message,
  onTryAgain,
}: {
  message: string;
  onTryAgain: () => void;
}) {
  return (
    <div
      role="alert"
      style={{
        background: '#fff7d6',
        color: '#7a5d00',
        border: '1px solid #f0c94c',
        borderRadius: 8,
        padding: 12,
        display: 'flex',
        flexDirection: 'column',
        gap: 8,
        fontSize: 13,
        lineHeight: 1.45,
      }}
    >
      <span>{message}</span>
      <button
        type="button"
        onClick={onTryAgain}
        style={{
          alignSelf: 'flex-start',
          background: '#fff',
          color: '#7a5d00',
          border: '1px solid #f0c94c',
          borderRadius: 6,
          padding: '6px 12px',
          fontSize: 13,
          fontWeight: 500,
          cursor: 'pointer',
        }}
      >
        Try different posting
      </button>
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
  const jobPostingRef = useRef<HTMLTextAreaElement | null>(null);

  const handleTryDifferentPosting = () => {
    setResult(null);
    setError(null);
    jobPostingRef.current?.focus();
    jobPostingRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  };

  const update =
    (key: ScalarFormKey) =>
    (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
      setForm((prev) => ({ ...prev, [key]: e.target.value }));

  const updateExperience =
    (idx: number, key: keyof ExperienceFormItem) =>
    (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
      setForm((prev) => ({
        ...prev,
        experience: prev.experience.map((exp, i) =>
          i === idx ? { ...exp, [key]: e.target.value } : exp,
        ),
      }));

  const addExperience = () =>
    setForm((prev) =>
      prev.experience.length >= MAX_EXPERIENCE
        ? prev
        : { ...prev, experience: [...prev.experience, { ...EMPTY_EXPERIENCE }] },
    );

  const removeExperience = (idx: number) =>
    setForm((prev) => ({
      ...prev,
      experience: prev.experience.filter((_, i) => i !== idx),
    }));

  const updateEducation =
    (idx: number, key: keyof EducationFormItem) =>
    (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
      setForm((prev) => ({
        ...prev,
        education: prev.education.map((edu, i) =>
          i === idx ? { ...edu, [key]: e.target.value } : edu,
        ),
      }));

  const addEducation = () =>
    setForm((prev) =>
      prev.education.length >= MAX_EDUCATION
        ? prev
        : { ...prev, education: [...prev.education, { ...EMPTY_EDUCATION }] },
    );

  const removeEducation = (idx: number) =>
    setForm((prev) => ({
      ...prev,
      education: prev.education.filter((_, i) => i !== idx),
    }));

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      // Use `/` as separator when present so skill groups like
      // "Backend: Python, FastAPI / Frontend: React" reach the template intact;
      // otherwise fall back to the simple comma-separated flat list.
      const skillsSeparator = form.skillsCsv.includes('/') ? '/' : ',';
      const skills = form.skillsCsv
        .split(skillsSeparator)
        .map((s) => s.trim())
        .filter(Boolean);
      const response = await generateCV({
        job_posting: jobPosting,
        user_profile: {
          name: form.name.trim(),
          email: form.email.trim() || undefined,
          location: form.location.trim() || undefined,
          summary: form.summary.trim() || undefined,
          linkedin: form.linkedin.trim() || undefined,
          github: form.github.trim() || undefined,
          skills,
          experience: buildExperiencePayload(form),
          education: buildEducationPayload(form),
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
            ref={jobPostingRef}
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

        <Field label="Summary">
          <textarea
            value={form.summary}
            onChange={update('summary')}
            rows={3}
            placeholder="Breve descripción de tu perfil profesional"
            style={textareaStyle}
          />
        </Field>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <Field label="LinkedIn">
            <input
              value={form.linkedin}
              onChange={update('linkedin')}
              placeholder="linkedin.com/in/tu-perfil"
              style={inputStyle}
            />
          </Field>
          <Field label="GitHub">
            <input
              value={form.github}
              onChange={update('github')}
              placeholder="github.com/tu-usuario"
              style={inputStyle}
            />
          </Field>
        </div>

        <Field label="Skills (comma-separated)">
          <input
            value={form.skillsCsv}
            onChange={update('skillsCsv')}
            placeholder="Backend: Python, FastAPI / Frontend: React, TypeScript"
            style={inputStyle}
          />
        </Field>

        {form.experience.map((exp, idx) => (
          <fieldset key={idx} style={fieldsetStyle}>
            <legend style={{ fontWeight: 600, fontSize: 13, padding: '0 6px' }}>
              Experiencia {idx + 1}
            </legend>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
              <Field label="Title">
                <input
                  value={exp.title}
                  onChange={updateExperience(idx, 'title')}
                  style={inputStyle}
                />
              </Field>
              <Field label="Company">
                <input
                  value={exp.company}
                  onChange={updateExperience(idx, 'company')}
                  style={inputStyle}
                />
              </Field>
              <Field label="Start">
                <input
                  value={exp.start}
                  onChange={updateExperience(idx, 'start')}
                  placeholder="2022-01"
                  style={inputStyle}
                />
              </Field>
              <Field label="End">
                <input
                  value={exp.end}
                  onChange={updateExperience(idx, 'end')}
                  style={inputStyle}
                />
              </Field>
            </div>
            <Field label="Bullets (one per line)">
              <textarea
                value={exp.bulletsRaw}
                onChange={updateExperience(idx, 'bulletsRaw')}
                rows={5}
                placeholder={'Built X to reduce Y by 30%\nLed migration from A to B'}
                style={textareaStyle}
              />
            </Field>
            {form.experience.length > 1 && (
              <button
                type="button"
                onClick={() => removeExperience(idx)}
                style={removeButton}
              >
                Eliminar experiencia
              </button>
            )}
          </fieldset>
        ))}

        {form.experience.length < MAX_EXPERIENCE && (
          <button type="button" onClick={addExperience} style={ghostButton}>
            + Agregar experiencia
          </button>
        )}

        {form.education.map((edu, idx) => (
          <fieldset key={idx} style={fieldsetStyle}>
            <legend style={{ fontWeight: 600, fontSize: 13, padding: '0 6px' }}>
              Educación {idx + 1}
            </legend>
            <div
              style={{ display: 'grid', gridTemplateColumns: '2fr 2fr 1fr', gap: 12 }}
            >
              <Field label="Institution">
                <input
                  value={edu.institution}
                  onChange={updateEducation(idx, 'institution')}
                  style={inputStyle}
                />
              </Field>
              <Field label="Degree">
                <input
                  value={edu.degree}
                  onChange={updateEducation(idx, 'degree')}
                  style={inputStyle}
                />
              </Field>
              <Field label="Year">
                <input
                  value={edu.year}
                  onChange={updateEducation(idx, 'year')}
                  placeholder="2024"
                  style={inputStyle}
                />
              </Field>
            </div>
            <button
              type="button"
              onClick={() => removeEducation(idx)}
              style={removeButton}
            >
              Eliminar educación
            </button>
          </fieldset>
        ))}

        {form.education.length < MAX_EDUCATION && (
          <button type="button" onClick={addEducation} style={ghostButton}>
            + Agregar educación
          </button>
        )}

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
            {result.mismatch_warning && (
              <MismatchBanner
                message={result.mismatch_warning}
                onTryAgain={handleTryDifferentPosting}
              />
            )}
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

const ghostButton: React.CSSProperties = {
  background: '#fff',
  color: '#111',
  border: '1px dashed #b8b8c0',
  borderRadius: 8,
  padding: '10px 14px',
  fontSize: 13,
  fontWeight: 500,
  cursor: 'pointer',
  alignSelf: 'flex-start',
};

const removeButton: React.CSSProperties = {
  background: 'transparent',
  color: '#b3261e',
  border: '1px solid #f5c2bd',
  borderRadius: 6,
  padding: '4px 10px',
  fontSize: 12,
  cursor: 'pointer',
  alignSelf: 'flex-start',
};
