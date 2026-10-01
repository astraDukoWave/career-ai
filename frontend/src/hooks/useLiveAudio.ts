// useLiveAudio — the live interview audio pipeline (C2-SPEC-01 REQ-01/02).
//
// Captures the meeting tab (getDisplayMedia; the video track is dropped) or
// the microphone, turns it into 16 kHz mono PCM frames in an AudioWorklet
// (src/audio/pcm-worklet.js) and streams them over /api/interview/ws/live.
// Every server message goes to `onMessage`, tagged with the connection
// number so turn ids from a reconnection never collide with older ones.
//
// A hook (not a service) so unmount always stops the tracks, the audio graph
// and the socket: Chrome keeps its "sharing" bar and the mic LED on otherwise.
//
// Reconnection (EDGE-05/08): if the socket drops without an error message,
// it reconnects once and sends `start` again; the turn in progress is lost.
// That one reconnection keeps knocking with backoff for up to 25 s, long
// enough for a dyno restart, before giving up.

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  type InterviewContext,
  type LiveServerMessage,
  type LiveSource,
  liveSocketUrl,
  liveStartMessage,
  parseLiveMessage,
} from '../api/client';

export type LiveStatus = 'idle' | 'starting' | 'live' | 'reconnecting' | 'stopping';

export type LiveEnd =
  | { kind: 'stopped' }
  | { kind: 'source_ended'; source: LiveSource } // "Stop sharing", or the mic went away
  | { kind: 'error'; code: string; limitS?: number; maxSessions?: number }
  | { kind: 'connection_lost' };

export class AudioSourceError extends Error {
  constructor(
    public reason: 'denied' | 'busy' | 'no_audio' | 'not_a_tab' | 'unsupported',
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

// Hashed by Vite at build time, so a deploy never serves a stale worklet.
const WORKLET_URL = new URL('../audio/pcm-worklet.js', import.meta.url).href;
const MAX_BUFFERED_BYTES = 1 << 20; // a stalled socket drops audio instead of piling it up
const STOP_TIMEOUT_MS = 5000; // the server closes after flushing; this is the safety net
const RECONNECT_FIRST_DELAY_MS = 1000;
const RECONNECT_MAX_DELAY_MS = 5000;
const RECONNECT_WINDOW_MS = 25_000;

/** Raised when a session is abandoned before it started (the page went away or Stop). */
class Cancelled extends Error {}

function sourceError(err: unknown): AudioSourceError {
  const name = err instanceof DOMException ? err.name : '';
  if (name === 'NotAllowedError' || name === 'SecurityError') {
    return new AudioSourceError('denied', "Chrome didn't give access to the audio.");
  }
  if (name === 'NotReadableError') {
    return new AudioSourceError('busy', 'Another app is using that audio source. Close it and try again.');
  }
  if (name === 'NotFoundError' || name === 'OverconstrainedError') {
    return new AudioSourceError('busy', 'No microphone was found. Connect one and try again.');
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
      video: { displaySurface: 'browser' },
      audio: true,
      selfBrowserSurface: 'exclude',
      monitorTypeSurfaces: 'exclude',
      systemAudio: 'exclude',
    } as DisplayMediaStreamOptions;
    stream = await media.getDisplayMedia(options);
  } catch (err) {
    throw sourceError(err);
  }
  const surface = (stream.getVideoTracks()[0]?.getSettings() as { displaySurface?: string } | undefined)
    ?.displaySurface;
  for (const track of stream.getVideoTracks()) {
    track.stop();
    stream.removeTrack(track);
  }
  if (stream.getAudioTracks().length === 0) {
    stream.getTracks().forEach((t) => t.stop());
    // A window or the whole screen carries no audio on macOS (EDGE-02).
    if (surface === 'window' || surface === 'monitor') {
      throw new AudioSourceError('not_a_tab', 'A window or a screen was shared, and Chrome only gets audio from a tab.');
    }
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
  private reconnecting = false; // inside the one reconnection
  private reconnectUsed = false;
  private reconnectDeadline = 0;
  private reconnectAttempts = 0;
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

  private get abandoned(): boolean {
    return this.ended || this.stopping;
  }

  async begin(): Promise<void> {
    const [track] = this.stream.getAudioTracks();
    track.addEventListener('ended', () => {
      this.sourceEnded = true;
      this.stop();
    });
    const ctx = createContext();
    this.ctx = ctx;
    await ctx.audioWorklet.addModule(WORKLET_URL);
    if (this.abandoned) throw new Cancelled();
    const source = ctx.createMediaStreamSource(this.stream);
    const node = new AudioWorkletNode(ctx, 'pcm-frame-processor');
    this.node = node;
    // Pulled through a muted gain so Chrome keeps processing it; nothing is played.
    const mute = ctx.createGain();
    mute.gain.value = 0;
    source.connect(node).connect(mute).connect(ctx.destination);
    node.port.onmessage = (event: MessageEvent<ArrayBuffer>) => this.sendFrame(event.data);
    await ctx.resume();
    if (this.abandoned) throw new Cancelled();
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
        if (this.stopping) return;
        this.ready = true;
        this.reconnecting = false;
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
        this.finish(this.stoppedEnd());
      } else if (this.lastError) {
        const { code, limit_s, max_sessions } = this.lastError;
        this.finish({ kind: 'error', code, limitS: limit_s, maxSessions: max_sessions });
      } else if (!this.reconnectUsed || this.reconnecting) {
        this.scheduleReconnect();
      } else {
        this.finish({ kind: 'connection_lost' });
      }
    };
  }

  /** The one reconnection: retry the handshake with backoff inside a bounded window. */
  private scheduleReconnect(): void {
    if (!this.reconnectUsed) {
      this.reconnectUsed = true;
      this.reconnecting = true;
      this.reconnectDeadline = Date.now() + RECONNECT_WINDOW_MS;
    }
    if (Date.now() >= this.reconnectDeadline) {
      this.finish({ kind: 'connection_lost' });
      return;
    }
    const delay = Math.min(RECONNECT_FIRST_DELAY_MS * 2 ** this.reconnectAttempts, RECONNECT_MAX_DELAY_MS);
    this.reconnectAttempts += 1;
    this.handlers.onStatus('reconnecting');
    window.setTimeout(() => {
      if (!this.abandoned) this.open();
    }, delay);
  }

  private stoppedEnd(): LiveEnd {
    return this.sourceEnded ? { kind: 'source_ended', source: this.source } : { kind: 'stopped' };
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
    if (ws && ws.readyState === WebSocket.OPEN && this.ready) {
      this.handlers.onStatus('stopping');
      ws.send(JSON.stringify({ type: 'stop' }));
      this.stopTimer = window.setTimeout(() => ws.close(), STOP_TIMEOUT_MS);
    } else {
      this.finish(this.stoppedEnd());
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
  // Set by Stop during start-up and by unmount: a start still waiting for
  // the picker or the permission prompt must not come alive afterwards.
  const cancelRef = useRef(false);
  const unmountedRef = useRef(false);
  const connectionsRef = useRef(0);

  useEffect(() => {
    callbacksRef.current = callbacks;
  });

  const start = useCallback(async (source: LiveSource, context: InterviewContext | null) => {
    if (sessionRef.current || startingRef.current || unmountedRef.current) return;
    startingRef.current = true;
    cancelRef.current = false;
    setStatus('starting');
    try {
      let stream: MediaStream;
      try {
        stream = await acquire(source);
      } catch (err) {
        if (!unmountedRef.current) setStatus('idle');
        if (cancelRef.current || unmountedRef.current) return;
        throw err;
      }
      if (cancelRef.current || unmountedRef.current) {
        stream.getTracks().forEach((t) => t.stop());
        if (!unmountedRef.current) setStatus('idle');
        return;
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
      } catch (err) {
        session.dispose();
        if (err instanceof Cancelled || cancelRef.current || unmountedRef.current) return;
        throw new AudioSourceError('unsupported', "Couldn't start the audio processing in this browser.");
      }
    } finally {
      startingRef.current = false;
    }
  }, []);

  const stop = useCallback(() => {
    if (sessionRef.current) sessionRef.current.stop();
    else if (startingRef.current) cancelRef.current = true;
  }, []);

  // Unmount: release the tab/mic and the socket, even mid start-up.
  useEffect(() => {
    unmountedRef.current = false;
    return () => {
      unmountedRef.current = true;
      cancelRef.current = true;
      sessionRef.current?.dispose();
    };
  }, []);

  return { status, start, stop };
}
