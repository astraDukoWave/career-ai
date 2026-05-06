// InterviewCopilot — single-column page wrapping the SSE streaming flow.
//
// Layout (top to bottom):
//   1. Header
//   2. Textarea for the interviewer's prompt + "Get Suggestion" button
//   3. SuggestionPanel that fills with chunks as Gemini streams them
//
// No audio yet — that's Phase 2 of this sprint.

import { useRef, useState } from 'react';
import {
  ApiError,
  streamSuggestion,
  type SuggestionMeta,
} from '../api/client';
import SuggestionPanel from '../components/SuggestionPanel';

export default function InterviewCopilot() {
  const [text, setText] = useState('');
  const [content, setContent] = useState('');
  const [meta, setMeta] = useState<SuggestionMeta | null>(null);
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = text.trim();
    if (!trimmed || streaming) return;

    setContent('');
    setMeta(null);
    setError(null);
    setStreaming(true);

    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;

    try {
      await streamSuggestion(
        trimmed,
        {
          onMeta: setMeta,
          onChunk: (chunk) => setContent((prev) => prev + chunk),
          onError: (_code, detail) => setError(detail),
          onDone: () => setStreaming(false),
        },
        ctrl.signal,
      );
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        return;
      }
      const msg =
        err instanceof ApiError
          ? `${err.status} — ${err.message}`
          : err instanceof Error
            ? err.message
            : 'Unknown error';
      setError(msg);
      setStreaming(false);
    }
  };

  const onStop = () => {
    abortRef.current?.abort();
    setStreaming(false);
  };

  const canSubmit = !streaming && text.trim().length > 0;

  return (
    <div style={containerStyle}>
      <header style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        <h1 style={{ margin: 0, fontSize: 24 }}>Interview Copilot</h1>
        <p style={{ margin: 0, color: '#555' }}>
          Paste what the interviewer just said. We classify the intent and
          stream a tailored suggestion in real time.
        </p>
      </header>

      <form
        onSubmit={onSubmit}
        style={{ display: 'flex', flexDirection: 'column', gap: 12 }}
      >
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={6}
          placeholder="Paste the interviewer's question or prompt here…"
          style={textareaStyle}
        />
        <div style={{ display: 'flex', gap: 8 }}>
          <button type="submit" disabled={!canSubmit} style={primaryButton}>
            {streaming ? 'Streaming…' : 'Get Suggestion'}
          </button>
          {streaming && (
            <button type="button" onClick={onStop} style={secondaryButton}>
              Stop
            </button>
          )}
        </div>
      </form>

      <SuggestionPanel
        content={content}
        meta={meta}
        streaming={streaming}
        error={error}
      />
    </div>
  );
}

const containerStyle: React.CSSProperties = {
  maxWidth: 900,
  margin: '0 auto',
  padding: 24,
  display: 'flex',
  flexDirection: 'column',
  gap: 20,
};

const textareaStyle: React.CSSProperties = {
  border: '1px solid #d4d4d9',
  borderRadius: 6,
  padding: '10px 12px',
  fontSize: 15,
  fontFamily: 'inherit',
  resize: 'vertical',
  background: '#fff',
};

const primaryButton: React.CSSProperties = {
  background: '#111',
  color: '#fff',
  border: 'none',
  borderRadius: 8,
  padding: '12px 20px',
  fontSize: 15,
  fontWeight: 600,
};

const secondaryButton: React.CSSProperties = {
  background: '#fff',
  color: '#111',
  border: '1px solid #d4d4d9',
  borderRadius: 8,
  padding: '12px 20px',
  fontSize: 15,
  fontWeight: 500,
};
