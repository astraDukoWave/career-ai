// The live transcript as the interview-mode screen shows it (REQ-07).
//
// Pure: folds the server's partial/final/turn messages into a short list of
// turns. A turn's key is `${connection}:${turn_id}`, so a reconnection (which
// restarts the server's ids) never overwrites an earlier turn.

import type { LiveServerMessage } from '../api/client';

export interface TranscriptTurn {
  key: string;
  stable: string; // final text so far (the full question once the turn closes)
  partial: string; // unstable text still being recognised
  isQuestion: boolean;
  closed: boolean;
}

export const MAX_TURNS = 8;

export function turnKey(connection: number, turnId: number): string {
  return `${connection}:${turnId}`;
}

export function applyLiveMessage(
  turns: TranscriptTurn[],
  message: LiveServerMessage,
  connection: number,
): TranscriptTurn[] {
  if (message.type !== 'partial' && message.type !== 'final' && message.type !== 'turn') return turns;
  const key = turnKey(connection, message.turn_id);
  const index = turns.findIndex((t) => t.key === key);
  const current: TranscriptTurn =
    index >= 0 ? turns[index] : { key, stable: '', partial: '', isQuestion: false, closed: false };

  let next: TranscriptTurn | null;
  if (message.type === 'turn') {
    // The server's turn text is authoritative: the whole (possibly continued) turn.
    next = { ...current, stable: message.text, partial: '', isQuestion: message.is_question, closed: true };
  } else if (message.type === 'partial') {
    if (message.text) {
      next = { ...current, partial: message.text, closed: false };
    } else {
      // The server discarded text that never became final (noise): a new
      // turn disappears; a continued one goes back to its closed text.
      next = current.stable ? { ...current, partial: '', closed: true } : null;
    }
  } else {
    next = {
      ...current,
      stable: current.stable ? `${current.stable} ${message.text}` : message.text,
      partial: '',
      closed: false,
    };
  }

  if (next === null) return index >= 0 ? turns.filter((_, i) => i !== index) : turns;
  const changed: TranscriptTurn = next;
  const updated = index >= 0 ? turns.map((t, i) => (i === index ? changed : t)) : [...turns, changed];
  return updated.slice(-MAX_TURNS);
}

/** What "Suggest now" sends: the latest turn's words, closed or not. */
export function latestText(turns: TranscriptTurn[]): { key: string; text: string } | null {
  for (let i = turns.length - 1; i >= 0; i--) {
    const turn = turns[i];
    const text = [turn.stable, turn.partial].filter(Boolean).join(' ').trim();
    if (text) return { key: turn.key, text };
  }
  return null;
}
