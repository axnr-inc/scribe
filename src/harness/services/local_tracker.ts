/**
 * Local (no-op-ish) tracker fallback.
 *
 * In the original harness this file is used when the `@exp-logger/tracker`
 * remote-logging package isn't installed — `run.ts` tries to import it and
 * falls back to this local implementation that just produces deterministic
 * session hashes, tracks turn wall-time, and writes a tiny `experiment.json`.
 *
 * scribe doesn't use the remote tracker at all — `run.ts` writes everything
 * we need (per-task summary, manifest, session log) directly. This file is
 * kept ONLY for type compatibility: a few interfaces (`TurnHandle`,
 * `SessionHandle`, `ExperimentHandle`) are referenced indirectly through
 * pi-agent-core types. If you trim the harness further, you can safely
 * delete this file as long as nothing imports its types.
 *
 * Not invoked in the current run path.
 */
export interface TurnHandle {
  turnNumber: number;
  attachToAgent: (_agent: unknown) => void;
  complete: (_payload: { answer: string; error: string | null }) => Promise<{ timeSeconds: number }>;
}

export interface SessionHandle {
  sessionHash: string;
  startTurn: (_question: string) => Promise<TurnHandle>;
  addTurnStats: (_timeSeconds: number, _cost: number) => void;
  complete: () => Promise<void>;
}

export interface ExperimentHandle {
  id: string;
  startSession: (_args: { question: string; questionId: string }) => Promise<SessionHandle>;
  addSessionStats: (_timeSeconds: number, _cost: number) => void;
  complete: () => Promise<void>;
}

export interface Tracker {
  startExperiment: (_args: { notes?: string }) => Promise<ExperimentHandle>;
  startAdhocSession: (_question: string) => Promise<SessionHandle>;
  resumeSession: (_hash: string) => Promise<SessionHandle>;
  shutdown: () => Promise<void>;
}

function nowSeconds(): number {
  return Date.now() / 1000;
}

function randomId(prefix: string): string {
  return `${prefix}_${Math.random().toString(36).slice(2, 10)}`;
}

function createTurn(turnNumber: number): TurnHandle {
  const startedAt = nowSeconds();
  return {
    turnNumber,
    attachToAgent: () => {},
    async complete() {
      const timeSeconds = Math.max(0, nowSeconds() - startedAt);
      return { timeSeconds };
    },
  };
}

function createSession(sessionHash?: string): SessionHandle {
  let turns = 0;
  return {
    sessionHash: sessionHash || randomId("local_session"),
    async startTurn() {
      turns += 1;
      return createTurn(turns);
    },
    addTurnStats: () => {},
    async complete() {},
  };
}

export function createLocalTracker(): Tracker {
  return {
    async startExperiment() {
      return {
        id: randomId("local_experiment"),
        async startSession() {
          return createSession();
        },
        addSessionStats: () => {},
        async complete() {},
      };
    },
    async startAdhocSession() {
      return createSession();
    },
    async resumeSession(hash: string) {
      return createSession(hash);
    },
    async shutdown() {},
  };
}
