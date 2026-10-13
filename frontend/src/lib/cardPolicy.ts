// What a closed turn does to the suggestion card (REQ-04, REQ-07).
//
// Pure. With the meeting tab only the interviewer is heard, so the card
// follows the conversation by itself: a new question replaces it and a
// question that went on after a pause restarts it (v1.1).
//
// With the microphone the candidate is heard too, and the copilot cannot
// tell the two voices apart. So once a card is on screen it stays put while
// the candidate answers: a newer question, or more words on the same one,
// waits in a bar until the candidate opens it (v1.2).

export interface ActiveCard {
  key: string;
  question: string;
  auto: boolean;
}

export interface PendingQuestion {
  key: string;
  text: string;
  auto: boolean;
  /** More words for the card on screen, not a new question. */
  continued: boolean;
}

export type TurnAction =
  | { kind: 'ignore' }
  | { kind: 'suggest'; key: string; text: string; auto: boolean }
  | { kind: 'wait'; pending: PendingQuestion };

export interface ClosedTurn {
  key: string;
  text: string;
  isQuestion: boolean;
}

/**
 * `active` is the card on screen (or null). `hold` is true when that card
 * must not change by itself: microphone mode, after the session's first card.
 */
export function actionForTurn(turn: ClosedTurn, active: ActiveCard | null, hold: boolean): TurnAction {
  const continued = active !== null && active.key === turn.key;
  if (continued) {
    if (active.question === turn.text) return { kind: 'ignore' };
  } else if (!turn.isQuestion) {
    return { kind: 'ignore' };
  }
  const auto = continued ? active.auto : true;
  if (hold) return { kind: 'wait', pending: { key: turn.key, text: turn.text, auto, continued } };
  return { kind: 'suggest', key: turn.key, text: turn.text, auto };
}

/** The end of a long text, cut at a word, for a narrow card. */
export function tail(text: string, max: number): string {
  if (text.length <= max) return text;
  const cut = text.slice(-max);
  const space = cut.indexOf(' ');
  return `…${space >= 0 ? cut.slice(space + 1) : cut}`;
}
