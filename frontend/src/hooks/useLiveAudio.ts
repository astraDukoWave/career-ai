// useLiveAudio — the live interview audio pipeline (C2-SPEC-01 REQ-01/02).
//
// Captures the meeting tab (getDisplayMedia; the video track is dropped) or
// the microphone, turns it into 16 kHz mono PCM frames in an AudioWorklet
// (public/pcm-worklet.js) and streams them over /api/interview/ws/live.
// Every server message goes to `onMessage`, tagged with the connection
// number so turn ids from a reconnection never collide with older ones.
//
// A hook (not a service) so unmount always stops the tracks, the audio graph
// and the socket: Chrome keeps its "sharing" bar and the mic LED on otherwise.
//
// Reconnection (EDGE-05/08): if the socket drops without an error message,
// it reconnects once and sends `start` again; the turn in progress is lost.

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  type InterviewContext,
  type LiveServerMessage,
  type LiveSource,
  liveSocketUrl,
  liveStartMessage,
  parseLiveMessage,
} from '../api/client';

export type LiveStatus = 'idle' | 'starting' | 'live' | 'reconnecting';

export type LiveEnd =
  | { kind: 'stopped' }
  | { kind: 'source_ended' } // the user pressed Chrome's "Stop sharing"
  | { kind: 'error'; code: string; limitS?: number; maxSessions?: number }
  | { kind: 'connection_lost' };

export class AudioSourceError extends Error {
  constructor(
    public reason: 'denied' | 'no_audio' | 'unsupported',
    message: string,
  ) {
    super(message);
    this.name = 'AudioSourceError';
  }
}

export interface LiveCallbacks {
  onMessage: (message: LiveServerMessage, connection: number) => void;
  onEnd: (end: LiveEnd) => void;
}

const WORKLET_URL = '/pcm-worklet.js';
const MAX_BUFFERED_BYTES = 1 << 20; // a stalled socket drops audio instead of piling it up
const STOP_TIMEOUT_MS = 5000; // the server closes after flushing; this is the safety net
const RECONNECT_DELAY_MS = 1000;

function sourceError(err: unknown): AudioSourceError {
  const name = err instanceof DOMException ? err.name : '';
  if (name === 'NotAllowedError' || name === 'SecurityError') {
    return new AudioSourceError('denied', "Chrome didn't give access to the audio.");
  }
  if (name === 'NotFoundError' || name === 'NotReadableError' || name === 'OverconstrainedError') {
    return new AudioSourceError('denied', "Chrome couldn't read that audio source.");
  }
  return new AudioSourceError('unsupported', "This browser can't capture that audio.");
}

async function acquire(source: LiveSource): Promise<MediaStream> {
  const media = navigator.mediaDevices;
  if (source === 'mic') {
    if (!media?.getUserMedia) {
      throw new AudioSourceError('unsupported', "This browser can't use the microphone here.");
    }
    try {
      // No echo cancellation: the interviewer may be coming out of speakers.
      return await media.getUserMedia({
        audio: { channelCount: 1, echoCancellation: false, noiseSuppression: true, autoGainControl: true },
      });
    } catch (err) {
      throw sourceError(err);
    }
  }
  if (!media?.getDisplayMedia) {
    throw new AudioSourceError('unsupported', "This browser can't share a tab's audio. Use Chrome on a computer.");
  }
  let stream: MediaStream;
  try {
    // Chrome only shares tab audio together with video; the video is dropped
    // right away. Leave this copilot tab out of the picker.
    const options = {
      video: true,
      audio: true,
      selfBrowserSurface: 'exclude',
      systemAudio: 'exclude',
    } as DisplayMediaStreamOptions;
    stream = await media.getDisplayMedia(options);
  } catch (err) {
    throw sourceError(err);
  }
  for (const track of stream.getVideoTracks()) {
    track.stop();
    stream.removeTrack(track);
  }
  if (stream.getAudioTracks().length === 0) {
    stream.getTracks().forEach((t) => t.stop());
    throw new AudioSourceError('no_audio', 'The tab was shared without its audio.');
  }
  return stream;
}

function createContext(): AudioContext {
  try {
    // Chrome resamples to 16 kHz with a proper filter.
    return new AudioContext({ sampleRate: 16000 });
  } catch {
    return new AudioContext(); // the worklet resamples instead
  }
}

interface SessionHandlers {
  onStatus: (status: LiveStatus) => void;
  onMessage: (message: LiveServerMessage, connection: number) => void;
  onEnd: (end: LiveEnd) => void;
}

/** One live session: audio graph + socket, with one reconnection. */
class LiveSession {
  private ctx: AudioContext | null = null;
  private node: AudioWorkletNode | null = null;
  private ws: WebSocket | null = null;
  private ready = false;
  private reconnected = false;
  private stopping = false;
  private sourceEnded = false;
  private ended = false;
  private lastError: Extract<LiveServerMessage, { type: 'error' }> | null = null;
  private stopTimer: number | undefined;

  constructor(
    private stream: MediaStream,
    private source: LiveSource,
    private context: InterviewContext | null,
    private handlers: SessionHandlers,
    private nextConnection: () => number,
  ) {}

  async begin(): Promise<void> {
    const [track] = this.stream.getAudioTracks();
    track.addEventListener('ended', () => {
      this.sourceEnded = true;
      this.stop();
    });
    const ctx = createContext();
    this.ctx = ctx;
    await ctx.audioWorklet.addModule(WORKLET_URL);
    const source = ctx.createMediaStreamSource(this.stream);
    const node = new AudioWorkletNode(ctx, 'pcm-frame-processor');
    this.node = node;
    // Pulled through a muted gain so Chrome keeps processing it; nothing is played.
    const mute = ctx.createGain();
    mute.gain.value = 0;
    source.connect(node).connect(mute).connect(ctx.destination);
    node.port.onmessage = (event: MessageEvent<ArrayBuffer>) => this.sendFrame(event.data);
    await ctx.resume();
    this.open();
  }

  private open(): void {
    const connection = this.nextConnection();
    const ws = new WebSocket(liveSocketUrl());
    ws.binaryType = 'arraybuffer';
    this.ws = ws;
    this.ready = false;
    this.lastError = null;
    ws.onopen = () => ws.send(liveStartMessage(this.source, this.context));
    ws.onmessage = (event: MessageEvent) => {
      if (typeof event.data !== 'string') return;
      const message = parseLiveMessage(event.data);
      if (!message) return;
      if (message.type === 'ready') {
        this.ready = true;
        this.handlers.onStatus('live');
      } else if (message.type === 'error') {
        this.lastError = message;
      }
      this.handlers.onMessage(message, connection);
    };
    ws.onclose = () => {
      if (this.ws !== ws) return;
      this.ws = null;
      this.ready = false;
      if (this.stopping) {
        this.finish(this.sourceEnded ? { kind: 'source_ended' } : { kind: 'stopped' });
      } else if (this.lastError) {
        const { code, limit_s, max_sessions } = this.lastError;
        this.finish({ kind: 'error', code, limitS: limit_s, maxSessions: max_sessions });
      } else if (!this.reconnected && !this.ended) {
        this.reconnected = true;
        this.handlers.onStatus('reconnecting');
        window.setTimeout(() => {
          if (!this.ended && !this.stopping) this.open();
        }, RECONNECT_DELAY_MS);
      } else {
        this.finish({ kind: 'connection_lost' });
      }
    };
  }

  private sendFrame(frame: ArrayBuffer): void {
    const ws = this.ws;
    if (!ws || !this.ready || this.stopping || ws.readyState !== WebSocket.OPEN) return;
    if (ws.bufferedAmount > MAX_BUFFERED_BYTES) return;
    ws.send(frame);
  }

  /** Stop capturing now; let the server send the last turn, then close. */
  stop(): void {
    if (this.stopping || this.ended) return;
    this.stopping = true;
    this.releaseAudio();
    const ws = this.ws;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'stop' }));
      this.stopTimer = window.setTimeout(() => ws.close(), STOP_TIMEOUT_MS);
    } else {
      this.finish(this.sourceEnded ? { kind: 'source_ended' } : { kind: 'stopped' });
    }
  }

  dispose(): void {
    this.stopping = true;
    this.finish({ kind: 'stopped' });
  }

  private finish(end: LiveEnd): void {
    if (this.ended) return;
    this.ended = true;
    window.clearTimeout(this.stopTimer);
    this.releaseAudio();
    const ws = this.ws;
    this.ws = null;
    if (ws && ws.readyState !== WebSocket.CLOSED) ws.close();
    this.handlers.onEnd(end);
  }

  private releaseAudio(): void {
    this.stream.getTracks().forEach((t) => t.stop());
    if (this.node) {
      this.node.port.onmessage = null;
      this.node.disconnect();
      this.node = null;
    }
    if (this.ctx) {
      void this.ctx.close();
      this.ctx = null;
    }
  }
}

export interface UseLiveAudioResult {
  status: LiveStatus;
  /** Rejects with AudioSourceError when the audio can't be captured. */
  start: (source: LiveSource, context: InterviewContext | null) => Promise<void>;
  stop: () => void;
}

export function useLiveAudio(callbacks: LiveCallbacks): UseLiveAudioResult {
  const [status, setStatus] = useState<LiveStatus>('idle');
  const callbacksRef = useRef(callbacks);
  const sessionRef = useRef<LiveSession | null>(null);
  const startingRef = useRef(false);
  const connectionsRef = useRef(0);

  useEffect(() => {
    callbacksRef.current = callbacks;
  });

  const start = useCallback(async (source: LiveSource, context: InterviewContext | null) => {
    if (sessionRef.current || startingRef.current) return;
    startingRef.current = true;
    setStatus('starting');
    try {
      let stream: MediaStream;
      try {
        stream = await acquire(source);
      } catch (err) {
        setStatus('idle');
        throw err;
      }
      let begun = false;
      const session = new LiveSession(
        stream,
        source,
        context,
        {
          onStatus: setStatus,
          onMessage: (message, connection) => callbacksRef.current.onMessage(message, connection),
          onEnd: (end) => {
            if (sessionRef.current === session) sessionRef.current = null;
            setStatus('idle');
            if (begun) callbacksRef.current.onEnd(end);
          },
        },
        // Connection numbers never repeat on this page, so turn keys never collide.
        () => ++connectionsRef.current,
      );
      sessionRef.current = session;
      try {
        await session.begin();
        begun = true;
      } catch {
        session.dispose();
        throw new AudioSourceError('unsupported', "Couldn't start the audio processing in this browser.");
      }
    } finally {
      startingRef.current = false;
    }
  }, []);

  const stop = useCallback(() => sessionRef.current?.stop(), []);

  // Unmount: release the tab/mic and the socket.
  useEffect(() => () => sessionRef.current?.dispose(), []);

  return { status, start, stop };
}
