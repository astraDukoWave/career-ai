// InterviewCopilot — the Interview Copilot page, in two modes:
//
//   - Live interview (default, C2-SPEC-01): listens to the meeting tab or the
//     microphone, detects the interviewer's questions and streams a suggestion
//     on its own. Built for a narrow window next to the camera.
//   - Type a question: the original text mode, still available (REQ-07) and
//     the fallback whenever live mode is unavailable (NFR-06).
//
// Both modes send the Context Bridge (the last generated CV) with every
// suggestion, so answers only use the candidate's own facts.

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  ApiError,
  streamSuggestion,
  type SuggestionMeta,
} from '../api/client';
import LiveInterview from '../components/LiveInterview';
import type { LiveStatus } from '../hooks/useLiveAudio';
import SuggestionPanel from '../components/SuggestionPanel';
import {
  CONTEXT_STORAGE_KEY,
  clearContext,
  loadContext,
  type StoredContext,
} from '../lib/interviewContext';

type Mode = 'live' | 'text';

export default function InterviewCopilot() {
  const [text, setText] = useState('');
  const [content, setContent] = useState('');
  const [meta, setMeta] = useState<SuggestionMeta | null>(null);
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  // Context Bridge (REQ-05): the last generated CV, read once on mount.
  const [stored, setStored] = useState<StoredContext | null>(loadContext);

  // A CV generated in another tab updates this page's context too.
  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key === null || e.key === CONTEXT_STORAGE_KEY) setStored(loadContext());
    };
    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
  }, []);

  // In-app navigation, same mechanism as the NavBar in App.tsx.
  const goToCV = (e: React.MouseEvent) => {
    e.preventDefault();
    window.history.pushState({}, '', '/cv');
    window.dispatchEvent(new PopStateEvent('popstate'));
  };

  const forgetContext = () => {
    clearContext();
    setStored(null);
  };

  const [mode, setMode] = useState<Mode>('live');
  const [live, setLive] = useState<{ status: LiveStatus; notice: string | null }>({ status: 'idle', notice: null });
  const onLiveActivity = useCallback((activity: { status: LiveStatus; notice: string | null }) => setLive(activity), []);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const typeInstead = useCallback(() => {
    setMode('text');
    // Focus would otherwise drop to the page when the live panel hides.
    window.setTimeout(() => textareaRef.current?.focus(), 0);
  }, []);

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
        stored?.context ?? null,
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
      <header style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        <h1 style={{ margin: 0, fontSize: 24 }}>Interview Copilot</h1>
        <div role="group" aria-label="Mode" style={{ display: 'flex', gap: 8 }}>
          {(
            [
              ['live', 'Live interview'],
              ['text', 'Type a question'],
            ] as const
          ).map(([value, label]) => (
            <button
              key={value}
              type="button"
              aria-pressed={mode === value}
              onClick={() => setMode(value)}
              style={mode === value ? tabOn : tabOff}
            >
              {label}
              {value === 'live' && live.status !== 'idle' && (
                <span aria-label="(listening)" style={{ marginLeft: 6, color: '#1f8b4c' }}>
                  ●
                </span>
              )}
            </button>
          ))}
        </div>
      </header>

      <div
        role="status"
        style={stored ? contextBannerStyle : noContextBannerStyle}
      >
        {stored ? (
          <>
            <span>
              <strong>Context:</strong>{' '}
              {stored.context.job_title || 'Untitled role'} — from your last CV (
              {new Date(stored.savedAt).toLocaleDateString()}). Suggestions only
              use facts from it.
            </span>
            <button type="button" onClick={forgetContext} style={linkButton}>
              Forget
            </button>
          </>
        ) : (
          <span>
            No CV context yet.{' '}
            <a href="/cv" onClick={goToCV}>
              Generate your CV
            </a>{' '}
            first for
            answers grounded in your own projects; until then, personal stories
            come back as [your real example: …] placeholders.
          </span>
        )}
      </div>

      {/* Live mode stays mounted while typing, so a session keeps running. */}
      <div hidden={mode !== 'live'}>
        <LiveInterview context={stored?.context ?? null} onTypeInstead={typeInstead} onActivity={onLiveActivity} />
      </div>

      <div hidden={mode !== 'text'} style={{ display: mode === 'text' ? 'flex' : 'none', flexDirection: 'column', gap: 20 }}>
      <form
        onSubmit={onSubmit}
        style={{ display: 'flex', flexDirection: 'column', gap: 12 }}
      >
        {live.notice && (
          <p role="status" style={{ margin: 0, fontSize: 14, color: '#8a5a00' }}>
            Live mode: {live.notice}
          </p>
        )}
        <p style={{ margin: 0, color: '#555' }}>
          Paste what the interviewer just said to get a suggested answer.
        </p>
        <textarea
          ref={textareaRef}
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
    </div>
  );
}

const tabBase: React.CSSProperties = {
  borderRadius: 8,
  padding: '8px 14px',
  fontSize: 14,
  fontWeight: 600,
  border: '1px solid #d4d4d9',
};

const tabOn: React.CSSProperties = { ...tabBase, background: '#111', color: '#fff', borderColor: '#111' };
const tabOff: React.CSSProperties = { ...tabBase, background: '#fff', color: '#111' };

const containerStyle: React.CSSProperties = {
  maxWidth: 640,
  margin: '0 auto',
  padding: 24,
  display: 'flex',
  flexDirection: 'column',
  gap: 20,
};

const contextBannerStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'space-between',
  gap: 12,
  padding: '10px 12px',
  borderRadius: 6,
  background: '#eef7f0',
  border: '1px solid #b9dcc3',
  fontSize: 14,
};

const noContextBannerStyle: React.CSSProperties = {
  ...contextBannerStyle,
  background: '#fff8e6',
  border: '1px solid #f0d58a',
};

const linkButton: React.CSSProperties = {
  background: 'none',
  border: 'none',
  color: '#0b57d0',
  cursor: 'pointer',
  fontSize: 14,
  padding: 0,
  whiteSpace: 'nowrap',
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
