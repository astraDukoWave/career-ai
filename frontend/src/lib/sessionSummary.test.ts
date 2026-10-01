import { describe, expect, it } from 'vitest';
import { percentile, type QuestionRecord, summarize, summaryText } from './sessionSummary';

const record = (overrides: Partial<QuestionRecord>): QuestionRecord => ({
  key: '1:1',
  question: 'Tell me about a project.',
  auto: true,
  askedAt: 0,
  firstChunkAt: null,
  feedback: null,
  ...overrides,
});

describe('percentile', () => {
  it('uses the nearest rank and handles no data', () => {
    expect(percentile([], 0.5)).toBeNull();
    expect(percentile([3, 1, 2], 0.5)).toBe(2);
    expect(percentile([1, 2, 3, 4], 0.5)).toBe(2);
    expect(percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 0.9)).toBe(9);
    expect(percentile([7], 0.9)).toBe(7);
  });
});

describe('summarize', () => {
  const start = new Date(2026, 8, 30, 18, 0);
  const end = new Date(2026, 8, 30, 18, 34, 20);

  it('counts questions, feedback and latency of automatic detections only', () => {
    const records = [
      record({ key: '1:1', askedAt: 1000, firstChunkAt: 2500, feedback: 'up' }),
      record({ key: '1:2', askedAt: 10_000, firstChunkAt: 12_000, feedback: 'up' }),
      record({ key: '1:3', askedAt: 20_000, firstChunkAt: 23_500, feedback: 'down' }),
      record({ key: '1:4', auto: false, askedAt: 30_000, firstChunkAt: 30_400 }), // Suggest now
      record({ key: '1:5', askedAt: 40_000, firstChunkAt: null }), // never answered
    ];
    const s = summarize(records, start, end);
    expect(s).toMatchObject({
      minutes: 34,
      questions: 5,
      auto: 4,
      manual: 1,
      rated: 3,
      useful: 2,
      notUseful: 1,
      latencyCount: 3,
    });
    expect(s.latencyP50).toBeCloseTo(2.0);
    expect(s.latencyP90).toBeCloseTo(3.5);
  });

  it('reports an empty session without inventing numbers', () => {
    const s = summarize([], start, start);
    expect(s).toMatchObject({ questions: 0, rated: 0, latencyP50: null, latencyP90: null, minutes: 0 });
    expect(summaryText(s)).toContain('p50 n/a, p90 n/a (0 questions)');
  });
});

describe('summaryText', () => {
  it('has the numbers and the fields to fill in the experiment log', () => {
    const s = summarize(
      [record({ askedAt: 0, firstChunkAt: 1800, feedback: 'up' })],
      new Date(2026, 8, 30, 18, 5),
      new Date(2026, 8, 30, 18, 45),
    );
    const text = summaryText(s);
    expect(text).toBe(
      [
        'CareerAI interview session, 2026-09-30 18:05 (40 min)',
        'Questions: 1 (1 detected automatically, 0 with Suggest now)',
        'Useful: 1 of 1 rated (0 not useful)',
        'Latency, end of question to first words: p50 1.8 s, p90 1.8 s (1 questions)',
        'Company and role:',
        'Platform (Meet, Zoom web, Teams web, other):',
        'AI tools allowed in this interview (yes, no, unknown):',
        'Stage:',
        'Outcome:',
      ].join('\n'),
    );
  });
});
