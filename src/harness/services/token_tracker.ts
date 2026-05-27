/**
 * Tracks token usage and estimates $ cost per session.
 *
 * Updated every `message_end` event (see `run.ts` agent.subscribe) with the
 * Anthropic-shaped usage object from pi-ai. We split out:
 *   - input_tokens             (regular non-cached input)
 *   - output_tokens
 *   - cache_read_input_tokens  (cache hits = cheap)
 *   - cache_creation_input_tokens (5-minute cache writes)
 *
 * `PRICING` is a hard-coded table of $-per-1M-tokens for known model IDs. If
 * the configured model isn't in the table, cost will report as 0 but token
 * counts are still tracked. Update this map when new model versions ship.
 *
 * `computeCost().total` returns the cumulative $ for the session — what we
 * print at the end of each task in `runOneTask`.
 *
 * NOTE: OpenRouter pricing is NOT in this table — for scribe Kimi runs,
 * cost is logged as 0. We get the actual cost from OpenRouter's invoice or
 * dashboard separately.
 */
import type { AgentMessage } from "@mariozechner/pi-agent-core";

export interface TokenUsage {
  input_tokens: number;
  output_tokens: number;
  cache_read_input_tokens: number;
  cache_creation_input_tokens: number;
}

interface ModelPricing {
  input: number;
  output: number;
  cacheWrite5m: number;
  cacheHit: number;
}

const PRICING: Record<string, ModelPricing> = {
  "claude-opus-4-6":   { input: 5,  output: 25, cacheWrite5m: 6.25,  cacheHit: 0.50 },
  "claude-opus-4-5":   { input: 5,  output: 25, cacheWrite5m: 6.25,  cacheHit: 0.50 },
  "claude-sonnet-4-6": { input: 3,  output: 15, cacheWrite5m: 3.75,  cacheHit: 0.30 },
  "claude-sonnet-4-5": { input: 3,  output: 15, cacheWrite5m: 3.75,  cacheHit: 0.30 },
  "claude-sonnet-4":   { input: 3,  output: 15, cacheWrite5m: 3.75,  cacheHit: 0.30 },
  "claude-haiku-4-5":  { input: 1,  output: 5,  cacheWrite5m: 1.25,  cacheHit: 0.10 },
};

export interface CostBreakdown {
  input: number;
  output: number;
  cacheWrite: number;
  cacheRead: number;
  total: number;
}

export class TokenTracker {
  private _input = 0;
  private _output = 0;
  private _cacheRead = 0;
  private _cacheCreation = 0;
  private _model: string;
  private _lastContextTokens = 0;
  private _lastMessageCount = 0;
  private _callCount = 0;

  constructor(model: string = "claude-sonnet-4-6") {
    this._model = model;
  }

  update(usage: Partial<TokenUsage>): void {
    this._input += usage.input_tokens ?? 0;
    this._output += usage.output_tokens ?? 0;
    this._cacheRead += usage.cache_read_input_tokens ?? 0;
    this._cacheCreation += usage.cache_creation_input_tokens ?? 0;
    this._callCount++;
  }

  recordLastResponse(inputTokens: number, outputTokens: number, messageCount: number): void {
    this._lastContextTokens = inputTokens + outputTokens;
    this._lastMessageCount = messageCount;
  }

  estimateContextTokens(messages: AgentMessage[]): number {
    if (this._lastContextTokens === 0) {
      return Math.ceil(JSON.stringify(messages).length / 4);
    }
    const newMessages = messages.slice(this._lastMessageCount);
    const deltaEstimate = newMessages.length > 0 ? Math.ceil(JSON.stringify(newMessages).length / 4) : 0;
    return this._lastContextTokens + deltaEstimate;
  }

  get inputTokens(): number { return this._input; }
  get outputTokens(): number { return this._output; }
  get cacheReadTokens(): number { return this._cacheRead; }
  get cacheCreationTokens(): number { return this._cacheCreation; }
  get totalTokens(): number { return this._input + this._output; }
  get lastContextTokens(): number { return this._lastContextTokens; }
  get callCount(): number { return this._callCount; }

  get uncachedInputTokens(): number {
    return Math.max(0, this._input - this._cacheRead - this._cacheCreation);
  }

  computeCost(): CostBreakdown {
    const p = PRICING[this._model] || PRICING["claude-sonnet-4-6"];
    const input = (this.uncachedInputTokens / 1_000_000) * p.input;
    const output = (this._output / 1_000_000) * p.output;
    const cacheWrite = (this._cacheCreation / 1_000_000) * p.cacheWrite5m;
    const cacheRead = (this._cacheRead / 1_000_000) * p.cacheHit;
    return { input, output, cacheWrite, cacheRead, total: input + output + cacheWrite + cacheRead };
  }

  computeCallCost(usage: Partial<TokenUsage>): number {
    const p = PRICING[this._model] || PRICING["claude-sonnet-4-6"];
    const uncached = Math.max(0, (usage.input_tokens ?? 0) - (usage.cache_read_input_tokens ?? 0) - (usage.cache_creation_input_tokens ?? 0));
    return (uncached / 1_000_000) * p.input
      + ((usage.output_tokens ?? 0) / 1_000_000) * p.output
      + ((usage.cache_creation_input_tokens ?? 0) / 1_000_000) * p.cacheWrite5m
      + ((usage.cache_read_input_tokens ?? 0) / 1_000_000) * p.cacheHit;
  }

  summary(): string {
    const cost = this.computeCost();
    return [
      `Tokens: ${this._input} in, ${this._output} out (${this.uncachedInputTokens} uncached, ${this._cacheRead} cache hits, ${this._cacheCreation} cache writes)`,
      `Context window (last turn): ${this._lastContextTokens.toLocaleString()} tokens`,
      `Cost: $${cost.total.toFixed(4)} (input: $${cost.input.toFixed(4)}, output: $${cost.output.toFixed(4)}, cache write: $${cost.cacheWrite.toFixed(4)}, cache read: $${cost.cacheRead.toFixed(4)})`,
    ].join("\n");
  }

  reset(): void {
    this._input = 0;
    this._output = 0;
    this._cacheRead = 0;
    this._cacheCreation = 0;
    this._lastContextTokens = 0;
    this._lastMessageCount = 0;
    this._callCount = 0;
  }
}
