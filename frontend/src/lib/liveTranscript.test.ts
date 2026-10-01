import { describe, expect, it } from 'vitest';
import type { LiveServerMessage } from '../api/client';
import { applyLiveMessage, latestText, MAX_TURNS, type TranscriptTurn } from './liveTranscript';

const fold = (messages: LiveServerMessage[], connection = 1): TranscriptTurn[] =>
  messages.reduce<TranscriptTurn[]>((turns, m) => applyLiveMessage(turns, m, connection), []);

describe('applyLiveMessage', () => {
  it('shows partial text, then the final text, then the closed question', () => {
    const turns = fold([
      { type: 'partial', text: 'Can you walk', turn_id: 1 },
      { type: 'final', text: 'Can you walk me through', turn_id: 1 },
      { type: 'turn', text: 'Can you walk me through', is_question: true, turn_id: 1 },
    ]);
    expect(turns).toEqual([
      { key: '1:1', stable: 'Can you walk me through', partial: '', isQuestion: true, closed: true },
    ]);
  });

  it('keeps a continued question in one turn with the full text (REQ-04 v1.1)', () => {
    const turns = fold([
      { type: 'final', text: 'Can you walk me through', turn_id: 1 },
      { type: 'turn', text: 'Can you walk me through', is_question: true, turn_id: 1 },
      { type: 'partial', text: 'how you would', turn_id: 1 },
      { type: 'final', text: 'how you would design a rate limiter?', turn_id: 1 },
      { type: 'turn', text: 'Can you walk me through how you would design a rate limiter?', is_question: true, turn_id: 1 },
    ]);
    expect(turns).toHaveLength(1);
    expect(turns[0].stable).toBe('Can you walk me through how you would design a rate limiter?');
  });

  it('clears unstable text that never became final', () => {
    expect(fold([{ type: 'partial', text: 'uh', turn_id: 2 }, { type: 'partial', text: '', turn_id: 2 }])).toEqual([]);
    const kept = fold([
      { type: 'turn', text: 'What is a closure?', is_question: true, turn_id: 1 },
      { type: 'partial', text: 'uh', turn_id: 1 },
      { type: 'partial', text: '', turn_id: 1 },
    ]);
    expect(kept).toEqual([{ key: '1:1', stable: 'What is a closure?', partial: '', isQuestion: true, closed: true }]);
  });

  it('never mixes turns from a reconnection with older ones', () => {
    let turns = fold([{ type: 'turn', text: 'First question?', is_question: true, turn_id: 1 }], 1);
    turns = applyLiveMessage(turns, { type: 'turn', text: 'Second question?', is_question: true, turn_id: 1 }, 2);
    expect(turns.map((t) => t.key)).toEqual(['1:1', '2:1']);
  });

  it('keeps only the latest turns and ignores other messages', () => {
    const messages: LiveServerMessage[] = Array.from({ length: MAX_TURNS + 3 }, (_, i) => ({
      type: 'turn',
      text: `Q${i}?`,
      is_question: true,
      turn_id: i + 1,
    }));
    const turns = fold([{ type: 'ready' }, ...messages, { type: 'error', code: 'internal' }]);
    expect(turns).toHaveLength(MAX_TURNS);
    expect(turns[turns.length - 1].stable).toBe(`Q${MAX_TURNS + 2}?`);
  });
});

describe('latestText', () => {
  it('returns the last turn with words, closed or still being spoken', () => {
    expect(latestText([])).toBeNull();
    const turns = fold([
      { type: 'turn', text: 'What is a closure?', is_question: true, turn_id: 1 },
      { type: 'final', text: 'And how do you', turn_id: 2 },
      { type: 'partial', text: 'test it', turn_id: 2 },
    ]);
    expect(latestText(turns)).toEqual({ key: '1:2', text: 'And how do you test it' });
  });
});
