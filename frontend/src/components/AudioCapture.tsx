// AudioCapture — presentational microphone toggle with three visual states.
//
// The component owns nothing about MediaRecorder or WebSockets — that lives
// in the parent. It just renders the right look and forwards clicks.
//
// Styling:
//   - Inline styles for everything that can be expressed inline.
//   - One <style> element injected locally to define the @keyframes pulse,
//     because keyframes can't live in a React style attribute. The CSS lives
//     in this file (no external dependency) and React de-dupes the inserted
//     <style> nodes via stable text content.

import type { CSSProperties } from 'react';

export type AudioCaptureState = 'idle' | 'recording' | 'connecting';

interface AudioCaptureProps {
  state: AudioCaptureState;
  onStart: () => void;
  onStop: () => void;
}

const KEYFRAMES = `
@keyframes audio-capture-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.55; }
}
.audio-capture-btn--recording {
  animation: audio-capture-pulse 1.2s ease-in-out infinite;
}
`;

const buttonBase: CSSProperties = {
  border: 'none',
  borderRadius: 8,
  padding: '12px 20px',
  fontSize: 15,
  fontWeight: 600,
  color: '#fff',
  display: 'inline-flex',
  alignItems: 'center',
  justifyContent: 'center',
  gap: 8,
  minWidth: 200,
};

const stateStyles: Record<AudioCaptureState, CSSProperties> = {
  idle: { background: '#111', cursor: 'pointer' },
  recording: { background: '#dc2626', cursor: 'pointer' },
  connecting: { background: '#9ca3af', cursor: 'not-allowed' },
};

const stateLabels: Record<AudioCaptureState, string> = {
  idle: 'Start Recording',
  recording: '● Recording…',
  connecting: 'Connecting…',
};

export default function AudioCapture({
  state,
  onStart,
  onStop,
}: AudioCaptureProps) {
  const handleClick = () => {
    if (state === 'idle') onStart();
    else if (state === 'recording') onStop();
    // connecting: button is disabled, this branch is unreachable.
  };

  const style: CSSProperties = { ...buttonBase, ...stateStyles[state] };
  const className =
    state === 'recording' ? 'audio-capture-btn--recording' : undefined;

  return (
    <>
      <style>{KEYFRAMES}</style>
      <button
        type="button"
        onClick={handleClick}
        disabled={state === 'connecting'}
        className={className}
        style={style}
        aria-label={stateLabels[state]}
      >
        {stateLabels[state]}
      </button>
    </>
  );
}
