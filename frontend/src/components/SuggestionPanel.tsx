// Streaming display panel for the Interview Copilot.
//
// Receives content as it arrives from the SSE stream and renders it
// progressively — Gemini's chunks become visible character-by-character so
// the user can read the suggestion while the interviewer keeps talking.
//
// Pure presentation. State (content, streaming flag, errors, intent/language
// metadata) is owned by the parent page (InterviewCopilot.tsx).

import type { SuggestionMeta } from '../api/client';

interface SuggestionPanelProps {
  content: string;
  meta: SuggestionMeta | null;
  streaming: boolean;
  error: string | null;
}

const INTENT_LABELS: Record<SuggestionMeta['intent'], string> = {
  tech_code: 'Technical · Code',
  tech_concept: 'Technical · Concept',
  behavioral_star: 'Behavioral · STAR',
};

const LANGUAGE_LABELS: Record<SuggestionMeta['language'], string> = {
  en: 'English',
  es: 'Español',
};

export default function SuggestionPanel({
  content,
  meta,
  streaming,
  error,
}: SuggestionPanelProps) {
  const isEmpty = !content && !streaming && !error && !meta;

  if (isEmpty) {
    return (
      <div
        style={{
          border: '1px dashed #cfcfd4',
          borderRadius: 8,
          padding: 32,
          color: '#6b6b75',
          textAlign: 'center',
          background: '#fff',
          minHeight: 240,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        Paste what the interviewer just asked, then press{' '}
        <strong style={{ marginLeft: 4 }}>Get Suggestion</strong>.
      </div>
    );
  }

  return (
    <div
      style={{
        background: '#fff',
        border: '1px solid #e2e2e8',
        borderRadius: 12,
        padding: 20,
        display: 'flex',
        flexDirection: 'column',
        gap: 12,
        minHeight: 240,
      }}
    >
      {/* Inline keyframes — kept local so the global stylesheet stays untouched
          and this component remains self-contained. */}
      <style>
        {`@keyframes sp-blink { 0%,49% { opacity: 1 } 50%,100% { opacity: 0 } }`}
      </style>

      {(meta || streaming) && (
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {meta && <span style={pillStyle}>{INTENT_LABELS[meta.intent]}</span>}
          {meta && (
            <span style={pillStyle}>{LANGUAGE_LABELS[meta.language]}</span>
          )}
          {streaming && (
            <span style={{ ...pillStyle, color: '#1f8b4c', borderColor: '#bfe5cd' }}>
              Streaming…
            </span>
          )}
        </div>
      )}

      <div
        style={{
          whiteSpace: 'pre-wrap',
          fontSize: 14,
          lineHeight: 1.55,
          color: '#222',
          fontFamily: 'inherit',
          flex: 1,
        }}
      >
        {content}
        {streaming && (
          <span
            aria-hidden="true"
            style={{
              display: 'inline-block',
              marginLeft: 2,
              width: 8,
              height: 16,
              background: '#222',
              verticalAlign: 'text-bottom',
              animation: 'sp-blink 1s step-end infinite',
            }}
          />
        )}
      </div>

      {error && (
        <div
          role="alert"
          style={{
            background: '#fdecea',
            color: '#b3261e',
            border: '1px solid #f5c2bd',
            borderRadius: 6,
            padding: 10,
            fontSize: 13,
          }}
        >
          {error}
        </div>
      )}
    </div>
  );
}

const pillStyle: React.CSSProperties = {
  fontSize: 12,
  fontWeight: 500,
  color: '#444',
  background: '#f0f0f4',
  border: '1px solid #e2e2e8',
  borderRadius: 999,
  padding: '3px 10px',
};
