/**
 * Writes the agent's session log as JSONL — one event per line.
 *
 * Path: `<task_dir>/sessions/normal_agent.jsonl`. Every event is appended as it
 * happens (no buffering), so a crash mid-task still leaves a partial log we
 * can inspect.
 *
 * Event types we record:
 *   - `user_message`        — the question that started the task
 *   - `assistant_thinking`  — every <thinking> block from the model
 *   - `assistant_response`  — every text part of an assistant message
 *   - `tool_call`           — name + arguments of each tool invocation
 *   - `tool_call_result`    — the tool's return content
 *   - `compaction_summary`  — when pi-agent-core compacts old context (rare)
 *
 * Each entry carries an incrementing `id`, ISO `timestamp`, plus `turnId` and
 * `iterationId` so we can reconstruct turn boundaries when grading or
 * generating SFT trajectories from logs.
 *
 * Why JSONL: trivially streamable, line-grep'able, and easy to load row-by-row
 * in Python (see `scripts/grade.py`).
 */
import * as fs from "fs";
import * as path from "path";

export type EventType = "user_message" | "tool_call" | "tool_call_result" | "assistant_response" | "assistant_thinking" | "compaction_summary";

export interface JournalEntry {
  id: number;
  type: EventType;
  timestamp: string;
  content: string;
  turnId: number;
  iterationId: number;
  isCompactSummary: boolean;
  toolName?: string;
  toolArgs?: unknown;
  toolId?: string;
  resultType?: string;
}

export class SessionLogger {
  readonly filePath: string;
  private nextId = 1;
  private _turnId = 1;
  private _iterationId = 0;

  constructor(sandboxDir: string, agentType: string, agentId: string) {
    const sessionsDir = path.join(sandboxDir, "sessions");
    fs.mkdirSync(sessionsDir, { recursive: true });
    this.filePath = path.join(sessionsDir, `${agentType}_${agentId}.jsonl`);
  }

  get turnId(): number { return this._turnId; }
  get iterationId(): number { return this._iterationId; }

  incrementTurn(): void { this._turnId++; this._iterationId = 0; }
  incrementIteration(): void { this._iterationId++; }

  private append(entry: JournalEntry): void {
    fs.appendFileSync(this.filePath, JSON.stringify(entry) + "\n");
  }

  private makeEntry(type: EventType, content: string, extra?: Partial<JournalEntry>): JournalEntry {
    return {
      id: this.nextId++, type,
      timestamp: new Date().toISOString(),
      content, turnId: this._turnId, iterationId: this._iterationId,
      isCompactSummary: false, ...extra,
    };
  }

  logUserMessage(content: string): void { this.append(this.makeEntry("user_message", content)); }
  logToolCall(toolName: string, toolArgs: unknown, toolId: string): void { this.append(this.makeEntry("tool_call", toolName, { toolName, toolArgs, toolId })); }
  logToolResult(toolName: string, resultType: string, toolId: string, content: string): void { this.append(this.makeEntry("tool_call_result", content, { toolName, toolId, resultType })); }
  logAssistantResponse(content: string): void { this.append(this.makeEntry("assistant_response", content)); }
  logAssistantThinking(content: string): void { this.append(this.makeEntry("assistant_thinking", content)); }

  readAll(): JournalEntry[] {
    if (!fs.existsSync(this.filePath)) return [];
    return fs.readFileSync(this.filePath, "utf-8").split("\n").filter(Boolean).map(l => JSON.parse(l) as JournalEntry);
  }

  getLastId(): number { return this.nextId - 1; }
}
