// Live interview mode (C2-SPEC-01 REQ-01, REQ-04, REQ-07).
//
// Built for a narrow window next to the meeting camera: one glance shows the
// question just asked (marked like a highlighter) and one streamed answer.
// There is only ever one suggestion card. When a question continues after a
// pause, the server repeats its turn id with the full text and the card's
// suggestion restarts in place (REQ-04 v1.1).

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  type InterviewContext,
  type LiveSource,
  streamSuggestion,
  type SuggestionMeta,
} from '../api/client';
import { AudioSourceError, type LiveEnd, useLiveAudio } from '../hooks/useLiveAudio';
import { applyLiveMessage, latestText, type TranscriptTurn, turnKey } from '../lib/liveTranscript';

type Feedback = 'up' | 'down' | null;

interface Card {
  run: number;
  key: string;
  question: string;
  content: string;
  meta: SuggestionMeta | null;
  streaming: boolean;
  error: string | null;
  auto: boolean;
  feedback: Feedback;
}

interface Notice {
  text: string;
  action?: 'retry' | 'type';
}

const STATUS_TEXT = {
  idle: 'Not listening',
  starting: 'Connecting…',
  live: 'Listening',
  reconnecting: 'Reconnecting…',
} as const;

const INTENT_LABELS: Record<SuggestionMeta['intent'], string> = {
  tech_code: 'Code',
  tech_concept: 'Concept',
  behavioral_star: 'Behavioral',
};

function noticeForEnd(end: LiveEnd): Notice | null {
  switch (end.kind) {
    case 'stopped':
      return null;
    case 'source_ended':
      return { text: 'You stopped sharing the tab, so listening stopped.', action: 'retry' };
    case 'connection_lost':
      return {
        text: 'Lost the connection to CareerAI. Start listening again, or keep going by typing the question.',
        action: 'type',
      };
    case 'error':
      if (end.code === 'busy') {
        return {
          text: `Live mode is full right now (${end.maxSessions ?? 2} sessions running). Try again in a few minutes, or type the question.`,
          action: 'type',
        };
      }
      if (end.code === 'time_limit') {
        const minutes = Math.round((end.limitS ?? 5400) / 60);
        return { text: `This session reached its ${minutes}-minute limit. Start listening again to continue.`, action: 'retry' };
      }
      if (end.code === 'stt_unavailable') {
        return { text: "Live transcription isn't available right now. Keep going by typing the question.", action: 'type' };
      }
      return { text: 'Something went wrong with live mode. Keep going by typing the question.', action: 'type' };
  }
}

function noticeForSourceError(err: unknown): Notice {
  if (err instanceof AudioSourceError) {
    if (err.reason === 'no_audio') {
      return {
        text: 'The tab was shared without its audio. Share it again and turn on “Also share tab audio” in Chrome’s picker.',
        action: 'retry',
      };
    }
    if (err.reason === 'denied') return { text: `${err.message} Allow it and try again.`, action: 'retry' };
    return { text: err.message, action: 'type' };
  }
  return { text: 'Live mode could not start. Keep going by typing the question.', action: 'type' };
}

interface LiveInterviewProps {
  context: InterviewContext | null;
  onTypeInstead: () => void;
}

export default function LiveInterview({ context, onTypeInstead }: LiveInterviewProps) {
  const [source, setSource] = useState<LiveSource>('tab');
  const [notice, setNotice] = useState<Notice | null>(null);
  const [turns, setTurns] = useState<TranscriptTurn[]>([]);
  const [card, setCard] = useState<Card | null>(null);
  // The suggestion being streamed, read synchronously by message handlers.
  const activeRef = useRef<{ run: number; key: string; question: string; auto: boolean } | null>(null);
  const runRef = useRef(0);
  const abortRef = useRef<AbortController | null>(null);

  const suggest = useCallback(
    (key: string, question: string, auto: boolean) => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      const run = ++runRef.current;
      activeRef.current = { run, key, question, auto };
      setCard({ run, key, question, content: '', meta: null, streaming: true, error: null, auto, feedback: null });
      const patch = (change: (c: Card) => Card) =>
        setCard((c) => (c && c.run === run ? change(c) : c));
      streamSuggestion(
        question,
        {
          onMeta: (meta) => patch((c) => ({ ...c, meta })),
          onChunk: (chunk) => patch((c) => ({ ...c, content: c.content + chunk })),
          onError: (_code, detail) => patch((c) => ({ ...c, error: detail })),
          onDone: () => patch((c) => ({ ...c, streaming: false })),
        },
        controller.signal,
        context,
      ).catch((err: unknown) => {
        if (err instanceof DOMException && err.name === 'AbortError') return;
        const message = err instanceof Error ? err.message : 'Unknown error';
        patch((c) => ({ ...c, streaming: false, error: message }));
      });
    },
    [context],
  );

  const { status, start, stop } = useLiveAudio({
    onMessage: (message, connection) => {
      setTurns((current) => applyLiveMessage(current, message, connection));
      if (message.type !== 'turn') return;
      const key = turnKey(connection, message.turn_id);
      const active = activeRef.current;
      if (active?.key === key) {
        // The question went on after a pause: same card, full question.
        if (active.question !== message.text) suggest(key, message.text, active.auto);
      } else if (message.is_question) {
        suggest(key, message.text, true);
      }
    },
    onEnd: (end) => setNotice(noticeForEnd(end)),
  });

  // Leaving the page cancels a suggestion still streaming.
  useEffect(() => () => abortRef.current?.abort(), []);

  const onStart = async () => {
    setNotice(null);
    setTurns([]);
    try {
      await start(source, context);
    } catch (err) {
      setNotice(noticeForSourceError(err));
    }
  };

  const onSuggestNow = () => {
    const latest = latestText(turns);
    if (latest) suggest(latest.key, latest.text, false);
  };

  const setFeedback = (value: Exclude<Feedback, null>) =>
    setCard((c) => (c ? { ...c, feedback: c.feedback === value ? null : value } : c));

  const running = status !== 'idle';
  const canSuggestNow = latestText(turns) !== null;

  return (
    <section aria-label="Live interview" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 10 }}>
        <div role="radiogroup" aria-label="Audio source" style={segmented}>
          {(['tab', 'mic'] as const).map((value) => (
            <button
              key={value}
              type="button"
              role="radio"
              aria-checked={source === value}
              disabled={running}
              onClick={() => setSource(value)}
              style={source === value ? segmentOn : segmentOff}
            >
              {value === 'tab' ? 'Meeting tab' : 'Microphone'}
            </button>
          ))}
        </div>
        {running ? (
          <button type="button" onClick={stop} disabled={status === 'starting'} style={stopButton}>
            Stop listening
          </button>
        ) : (
          <button type="button" onClick={onStart} style={startButton}>
            Start listening
          </button>
        )}
        <span role="status" style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 13, color: '#55555f' }}>
          <span aria-hidden="true" style={{ ...dot, background: DOT_COLORS[status] }} />
          {STATUS_TEXT[status]}
        </span>
      </div>

      {!running && (
        <p style={hint}>
          {source === 'tab'
            ? 'Chrome asks which tab to share: pick the meeting and turn on “Also share tab audio”. Meeting in the Zoom or Teams app? Join it from the browser instead, or choose Microphone.'
            : 'The microphone hears you too. Use it with the interviewer on your speakers, or on a second device next to them.'}
        </p>
      )}

      {notice && (
        <div role="alert" style={noticeBox}>
          <span>{notice.text}</span>
          {notice.action === 'retry' && (
            <button type="button" onClick={onStart} style={linkButton}>
              Try again
            </button>
          )}
          {notice.action === 'type' && (
            <button type="button" onClick={onTypeInstead} style={linkButton}>
              Type a question
            </button>
          )}
        </div>
      )}

      <div aria-live="polite" style={cardBox}>
        {card ? (
          <>
            <p style={{ margin: 0, fontSize: 15, lineHeight: 1.5, fontWeight: 600 }}>
              <mark style={highlight}>{card.question}</mark>
            </p>
            {card.meta && (
              <span style={{ fontSize: 12, color: '#55555f' }}>{INTENT_LABELS[card.meta.intent]} question</span>
            )}
            <div style={{ whiteSpace: 'pre-wrap', fontSize: 16, lineHeight: 1.55, color: '#1c1c22' }}>
              {card.content || (card.streaming ? 'Thinking…' : '')}
            </div>
            {card.error && (
              <div role="alert" style={errorBox}>
                {card.error}
              </div>
            )}
          </>
        ) : (
          <p style={{ margin: 0, color: '#6b6b75', fontSize: 14 }}>
            When the interviewer asks a question, it shows up here with a suggested answer.
          </p>
        )}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 4 }}>
          {card && !card.streaming && !card.error && (
            <>
              <button
                type="button"
                aria-label="This helped"
                aria-pressed={card.feedback === 'up'}
                onClick={() => setFeedback('up')}
                style={card.feedback === 'up' ? thumbOn : thumbOff}
              >
                👍
              </button>
              <button
                type="button"
                aria-label="This didn't help"
                aria-pressed={card.feedback === 'down'}
                onClick={() => setFeedback('down')}
                style={card.feedback === 'down' ? thumbOn : thumbOff}
              >
                👎
              </button>
            </>
          )}
          <button
            type="button"
            onClick={onSuggestNow}
            disabled={!canSuggestNow}
            style={{ ...secondaryButton, marginLeft: 'auto' }}
            title="Suggest an answer to the last thing the interviewer said"
          >
            Suggest now
          </button>
        </div>
      </div>

      {turns.length > 0 && (
        <ol aria-label="Transcript" style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: 6 }}>
          {turns.map((turn) => (
            <li
              key={turn.key}
              style={{
                fontSize: 14,
                lineHeight: 1.5,
                paddingLeft: 10,
                borderLeft: `3px solid ${turn.isQuestion ? '#e8c547' : 'transparent'}`,
              }}
            >
              {turn.stable}
              {turn.partial && (
                <span style={{ color: '#9a9aa3' }}>
                  {turn.stable ? ' ' : ''}
                  {turn.partial}
                </span>
              )}
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

const DOT_COLORS = {
  idle: '#c4c4cc',
  starting: '#c4c4cc',
  live: '#1f8b4c',
  reconnecting: '#b7791f',
} as const;

const dot: React.CSSProperties = { width: 8, height: 8, borderRadius: '50%', display: 'inline-block' };

const segmented: React.CSSProperties = {
  display: 'inline-flex',
  border: '1px solid #d4d4d9',
  borderRadius: 8,
  overflow: 'hidden',
};

const segmentBase: React.CSSProperties = {
  border: 'none',
  padding: '9px 12px',
  fontSize: 14,
};

const segmentOn: React.CSSProperties = { ...segmentBase, background: '#111', color: '#fff' };
const segmentOff: React.CSSProperties = { ...segmentBase, background: '#fff', color: '#111' };

const startButton: React.CSSProperties = {
  background: '#111',
  color: '#fff',
  border: 'none',
  borderRadius: 8,
  padding: '10px 16px',
  fontSize: 14,
  fontWeight: 600,
};

const stopButton: React.CSSProperties = { ...startButton, background: '#b3261e' };

const secondaryButton: React.CSSProperties = {
  background: '#fff',
  color: '#111',
  border: '1px solid #d4d4d9',
  borderRadius: 8,
  padding: '8px 14px',
  fontSize: 14,
  fontWeight: 500,
};

const thumbOff: React.CSSProperties = {
  background: '#fff',
  border: '1px solid #d4d4d9',
  borderRadius: 8,
  padding: '6px 10px',
  fontSize: 15,
};

const thumbOn: React.CSSProperties = { ...thumbOff, background: '#eef7f0', borderColor: '#1f8b4c' };

const hint: React.CSSProperties = { margin: 0, fontSize: 13, color: '#55555f', lineHeight: 1.5 };

const noticeBox: React.CSSProperties = {
  display: 'flex',
  flexWrap: 'wrap',
  alignItems: 'center',
  gap: 10,
  padding: '10px 12px',
  borderRadius: 6,
  background: '#fff8e6',
  border: '1px solid #f0d58a',
  fontSize: 14,
};

const linkButton: React.CSSProperties = {
  background: 'none',
  border: 'none',
  color: '#0b57d0',
  padding: 0,
  fontSize: 14,
  fontWeight: 600,
};

const cardBox: React.CSSProperties = {
  background: '#fff',
  border: '1px solid #e2e2e8',
  borderRadius: 12,
  padding: 16,
  display: 'flex',
  flexDirection: 'column',
  gap: 10,
  minHeight: 160,
};

const highlight: React.CSSProperties = {
  background: '#fff3bf',
  color: 'inherit',
  padding: '1px 3px',
  boxDecorationBreak: 'clone',
  WebkitBoxDecorationBreak: 'clone',
};

const errorBox: React.CSSProperties = {
  background: '#fdecea',
  color: '#b3261e',
  border: '1px solid #f5c2bd',
  borderRadius: 6,
  padding: 10,
  fontSize: 13,
};
