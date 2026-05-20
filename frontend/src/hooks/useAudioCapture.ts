// useAudioCapture — wraps getUserMedia + MediaRecorder behind a tiny React API.
//
// Consumer contract:
//   const { isRecording, startRecording, stopRecording } =
//     useAudioCapture({ onChunk: (blob) => ws.send(blob) });
//
// Why a hook (and not a service): MediaStream/MediaRecorder are tied to the
// component lifecycle — they MUST be torn down on unmount or the browser
// keeps the mic LED on. A hook gives us a guaranteed cleanup hook.

import { useCallback, useEffect, useRef, useState } from 'react';

export interface UseAudioCaptureOptions {
  // Called once per recorded slice (~every `timesliceMs`). The blob is
  // raw `audio/webm;codecs=opus` in Chromium-based browsers.
  onChunk: (blob: Blob) => void;
  // How often MediaRecorder emits a chunk. Defaults to 2000ms to match
  // the cadence the backend WebSocket expects.
  timesliceMs?: number;
}

export interface UseAudioCaptureResult {
  isRecording: boolean;
  startRecording: () => Promise<void>;
  stopRecording: () => void;
}

const DEFAULT_TIMESLICE_MS = 2000;

export function useAudioCapture(
  options: UseAudioCaptureOptions,
): UseAudioCaptureResult {
  const { onChunk } = options;

  const [isRecording, setIsRecording] = useState<boolean>(false);

  const streamRef = useRef<MediaStream | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);


  // Stable ref to the latest onChunk so the recorder's ondataavailable
  // handler doesn't capture a stale closure when the parent re-renders
  // with a new callback identity.
  const onChunkRef = useRef<UseAudioCaptureOptions['onChunk']>(onChunk);
  useEffect(() => {
    onChunkRef.current = onChunk;
  }, [onChunk]);

  const stopRecording = useCallback((): void => {

    const recorder = recorderRef.current;
    if (recorder && recorder.state !== 'inactive') {
      recorder.stop();
    }
    recorderRef.current = null;

    const stream = streamRef.current;
    if (stream) {
      stream.getTracks().forEach((track) => track.stop());
    }
    streamRef.current = null;

    setIsRecording(false);
  }, []);

  const startRecording = useCallback(async (): Promise<void> => {
    if (recorderRef.current) {
      return;
    }

    // Throws on permission denial / no microphone. We propagate so the
    // caller can surface a UI error; isRecording stays false.
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    streamRef.current = stream;

    let recorder: MediaRecorder;
    try {
      recorder = new MediaRecorder(stream);
    } catch (err) {
      stream.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
      throw err;
    }

    recorder.ondataavailable = (event: BlobEvent) => {
      if (event.data && event.data.size > 0) {
        onChunkRef.current(event.data);
      }
    };

    recorderRef.current = recorder;
    recorder.start();
    setIsRecording(true);
  }, []);

  // Unmount cleanup. Inlined (instead of calling stopRecording) so this
  // effect has no deps and runs exactly once on teardown — keeping the
  // callback identities of start/stopRecording stable for consumers.
  useEffect(() => {
    return () => {

      const recorder = recorderRef.current;
      if (recorder && recorder.state !== 'inactive') {
        try {
          recorder.stop();
        } catch {
          // Already inactive due to a race — nothing to do.
        }
      }
      const stream = streamRef.current;
      if (stream) {
        stream.getTracks().forEach((t) => t.stop());
      }
      recorderRef.current = null;
      streamRef.current = null;
    };
  }, []);

  return { isRecording, startRecording, stopRecording };
}
