import { describe, expect, it } from 'vitest';
import { actionForTurn, tail } from './cardPolicy';

const q1 = { key: '1:1', text: 'Tell me about a project you are proud of.', isQuestion: true };
const card = { key: '1:1', question: q1.text, auto: true };

describe('meeting tab: the card follows the conversation', () => {
  it('starts a card for the first question', () => {
    expect(actionForTurn(q1, null, false)).toEqual({ kind: 'suggest', key: '1:1', text: q1.text, auto: true });
  });

  it('replaces the card when a new question arrives', () => {
    const q2 = { key: '1:2', text: 'How would you design a rate limiter?', isQuestion: true };
    expect(actionForTurn(q2, card, false)).toMatchObject({ kind: 'suggest', key: '1:2' });
  });

  it('restarts the card when its question went on after a pause', () => {
    const more = { key: '1:1', text: `${q1.text} And what was hard?`, isQuestion: true };
    expect(actionForTurn(more, card, false)).toEqual({ kind: 'suggest', key: '1:1', text: more.text, auto: true });
  });

  it('ignores statements and repeats', () => {
    expect(actionForTurn({ key: '1:2', text: 'Okay, great.', isQuestion: false }, card, false)).toEqual({ kind: 'ignore' });
    expect(actionForTurn(q1, card, false)).toEqual({ kind: 'ignore' });
  });
});

describe('microphone: the card stays put while the candidate answers', () => {
  it('still starts the first card by itself', () => {
    expect(actionForTurn(q1, null, false)).toMatchObject({ kind: 'suggest' });
  });

  it('a new question waits instead of replacing the card', () => {
    const q2 = { key: '1:2', text: '¿Cuál es tu expectativa salarial?', isQuestion: true };
    expect(actionForTurn(q2, card, true)).toEqual({
      kind: 'wait',
      pending: { key: '1:2', text: q2.text, auto: true, continued: false },
    });
  });

  it('the candidate answering right after the question does not restart the card', () => {
    const glued = { key: '1:1', text: `${q1.text} Sí, construí CareerAI con Claude Code.`, isQuestion: true };
    expect(actionForTurn(glued, card, true)).toEqual({
      kind: 'wait',
      pending: { key: '1:1', text: glued.text, auto: true, continued: true },
    });
  });

  it('what is not a question never reaches the bar', () => {
    expect(actionForTurn({ key: '1:3', text: 'Sí, claro.', isQuestion: false }, card, true)).toEqual({ kind: 'ignore' });
  });
});

describe('tail', () => {
  it('keeps short text whole and cuts long text at a word', () => {
    expect(tail('short', 10)).toBe('short');
    expect(tail('one two three four five', 12)).toBe('…four five');
  });
});
