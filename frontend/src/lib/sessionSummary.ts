// Session summary for the interview experiment (C2-SPEC-01 REQ-08, CS-6).
//
// Pure: the live screen records one entry per question it suggested on, and
// these functions turn them into the numbers the spec reviews after each real
// interview. Everything stays in the browser; nothing goes to the server.
//
// Latency (NFR-01) runs from the end of the question (the server's `turn`
// event, or its last repeat when the question continued) to the first words
// of the suggestion. Only questions detected automatically count: for
// "Suggest now" the end of the question is unknown.

export type Feedback = 'up' | 'down' | null;

export interface QuestionRecord {
  key: string;
  question: string;
  auto: boolean; // detected without a click
  askedAt: number; // ms (performance.now) when the suggestion (re)started
  firstChunkAt: number | null; // ms when its first words arrived
  feedback: Feedback;
}

export interface SessionSummary {
  startedAt: Date;
  minutes: number;
  questions: number;
  auto: number;
  manual: number;
  rated: number;
  useful: number;
  notUseful: number;
  latencyP50: number | null; // seconds
  latencyP90: number | null;
  latencyCount: number;
}

/** Nearest-rank percentile; null for no data. */
export function percentile(values: number[], q: number): number | null {
  if (values.length === 0) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const rank = Math.min(sorted.length, Math.max(1, Math.ceil(q * sorted.length)));
  return sorted[rank - 1];
}

export function summarize(records: QuestionRecord[], startedAt: Date, endedAt: Date): SessionSummary {
  const latencies = records
    .filter((r) => r.auto && r.firstChunkAt !== null)
    .map((r) => ((r.firstChunkAt as number) - r.askedAt) / 1000);
  const useful = records.filter((r) => r.feedback === 'up').length;
  const notUseful = records.filter((r) => r.feedback === 'down').length;
  const auto = records.filter((r) => r.auto).length;
  return {
    startedAt,
    minutes: Math.max(0, Math.round((endedAt.getTime() - startedAt.getTime()) / 60000)),
    questions: records.length,
    auto,
    manual: records.length - auto,
    rated: useful + notUseful,
    useful,
    notUseful,
    latencyP50: percentile(latencies, 0.5),
    latencyP90: percentile(latencies, 0.9),
    latencyCount: latencies.length,
  };
}

const seconds = (value: number | null): string => (value === null ? 'n/a' : `${value.toFixed(1)} s`);

function pad(n: number): string {
  return String(n).padStart(2, '0');
}

/** The text "Copy summary" puts on the clipboard, ready for the experiment log. */
export function summaryText(s: SessionSummary): string {
  const d = s.startedAt;
  const when = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  return [
    `CareerAI interview session, ${when} (${s.minutes} min)`,
    `Questions: ${s.questions} (${s.auto} detected automatically, ${s.manual} with Suggest now)`,
    `Useful: ${s.useful} of ${s.rated} rated (${s.notUseful} not useful)`,
    `Latency, end of question to first words: p50 ${seconds(s.latencyP50)}, p90 ${seconds(s.latencyP90)} (${s.latencyCount} questions)`,
    'Company and role:',
    'Platform (Meet, Zoom web, Teams web, other):',
    'AI tools allowed in this interview (yes, no, unknown):',
    'Stage:',
    'Outcome:',
  ].join('\n');
}
