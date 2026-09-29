// InterviewCopilot — single-column page combining manual text input with
// live audio capture.
//
// Layout (top to bottom):
//   1. Header
//   2. AudioCapture mic button + textarea + "Get Suggestion" button
//   3. SuggestionPanel that fills with chunks as Gemini streams them
//
// Audio path: MediaRecorder chunks -> WebSocket /api/interview/ws/audio ->
// (mock) STT service -> JSON {type:'transcript', text:'...'} -> appended to
// the textarea with a "[Transcribed]: " prefix. Manual typing stays fully
// independent of the audio flow — audio is additive.

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  ApiError,
  streamSuggestion,
  type SuggestionMeta,
} from '../api/client';
import AudioCapture, {
  type AudioCaptureState,
} from '../components/AudioCapture';
import SuggestionPanel from '../components/SuggestionPanel';
import { useAudioCapture } from '../hooks/useAudioCapture';
import {
  CONTEXT_STORAGE_KEY,
  clearContext,
  loadContext,
  type StoredContext,
} from '../lib/interviewContext';

// Mirrors the API_URL convention in client.ts: same env var, same fallback.
// `replace(/^http/, 'ws')` turns http://localhost:8000 -> ws://localhost:8000
// and https://*.app.github.dev -> wss://*.app.github.dev (Codespaces).
const WS_URL =
  (import.meta.env.VITE_API_URL ?? 'http://localhost:8000').replace(
    /^http/,
    'ws',
  ) + '/api/interview/ws/audio';

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

  // --- Audio capture + transcript WebSocket ---------------------------------
  const [connState, setConnState] = useState<AudioCaptureState>('idle');
  const wsRef = useRef<WebSocket | null>(null);

  const handleChunk = useCallback((blob: Blob) => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(blob);
    }
  }, []);

  const { startRecording, stopRecording } = useAudioCapture({
    onChunk: handleChunk,
  });

  const closeAudioWs = useCallback(() => {
    const ws = wsRef.current;
    wsRef.current = null;
    if (ws && ws.readyState !== WebSocket.CLOSED) {
      ws.close();
    }
  }, []);

  const handleAudioStart = useCallback(() => {
    if (connState !== 'idle') return;
    setError(null);
    setConnState('connecting');

    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    ws.onopen = () => {
      // If Stop was pressed before the socket opened, wsRef was cleared.
      if (wsRef.current !== ws) {
        ws.close();
        return;
      }
      startRecording().then(
        () => {
          if (wsRef.current === ws) setConnState('recording');
        },
        (err: unknown) => {
          const msg =
            err instanceof Error ? err.message : 'Microphone access failed.';
          setError(msg);
          ws.close();
          setConnState('idle');
        },
      );
    };

    ws.onmessage = (event: MessageEvent<string>) => {
      try {
        const data = JSON.parse(event.data) as {
          type?: string;
          text?: string;
        };
        if (
          data.type === 'transcript' &&
          typeof data.text === 'string' &&
          data.text.length > 0
        ) {
          setText(
            (prev) => prev + (prev ? '\n' : '') + '[Transcribed]: ' + data.text,
          );
        }
      } catch {
        // Drop malformed frames quietly — don't kill the stream over one.
      }
    };

    ws.onerror = () => {
      setError('Audio WebSocket connection failed.');
    };

    ws.onclose = () => {
      // Server-side close (or our own close()) — reset audio UI.
      if (wsRef.current === ws) {
        wsRef.current = null;
      }
      stopRecording();
      setConnState('idle');
    };
  }, [connState, startRecording, stopRecording]);

  const handleAudioStop = useCallback(() => {
    stopRecording();
    closeAudioWs();
    setConnState('idle');
  }, [closeAudioWs, stopRecording]);

  // Unmount: tear down audio + WS so the mic LED goes off and the server
  // gets a clean disconnect instead of a silent socket leak.
  useEffect(() => {
    return () => {
      closeAudioWs();
      stopRecording();
    };
  }, [closeAudioWs, stopRecording]);

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
      <header style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        <h1 style={{ margin: 0, fontSize: 24 }}>Interview Copilot</h1>
        <p style={{ margin: 0, color: '#555' }}>
          Paste what the interviewer just said. We classify the intent and
          stream a tailored suggestion in real time.
        </p>
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

      <form
        onSubmit={onSubmit}
        style={{ display: 'flex', flexDirection: 'column', gap: 12 }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <AudioCapture
            state={connState}
            onStart={handleAudioStart}
            onStop={handleAudioStop}
          />
          <span style={{ color: '#6b6b75', fontSize: 13 }}>
            Transcripts append below with a "[Transcribed]:" prefix.
          </span>
        </div>
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
