/**
 * Persistent Python REPL — one long-lived python3 child process per task.
 *
 * On startup the REPL:
 *   1. Loads the preamble file (typically `<task_dir>/preamble.py`) which sets
 *      `CONTEXT_DIR`, defines `context_path(...)`, and imports pd/np/json/csv/os.
 *   2. Prints a READY sentinel so we know the preamble booted cleanly.
 *
 * On each `execute(code)` call:
 *   1. Sends the code over stdin with a `__REPL_EXEC__` marker.
 *   2. The Python wrapper exec()s the code in a persistent namespace `_ns`, so
 *      variables/DataFrames persist across calls within the same task.
 *   3. Captures stdout+stderr, then emits an END_OK or END_ERR sentinel.
 *   4. We collect output until the sentinel and return it.
 *
 * Why a persistent REPL (vs spawning a fresh `python` each call):
 *   - Avoids re-loading payments.csv (50 MB) every tool call — saves minutes per
 *     task on DABStep.
 *   - Keeps intermediate variables, function definitions, and computed
 *     filters across calls — matches the agentic "explore then compute" pattern.
 *
 * Killed at end-of-task via `repl.kill()` (called from `runOneTask` in run.ts).
 *
 * The 5-minute per-call timeout protects us from infinite loops in agent code.
 */
import * as fs from "fs";
import * as path from "path";
import * as os from "os";
import { spawn, type ChildProcess } from "child_process";

const END_OK = "__REPL_OK__";
const END_ERR = "__REPL_ERR__";
const READY = "__REPL_READY__";

const WRAPPER_CODE = [
  `import sys, traceback, io`,
  ``,
  `_ns = {}`,
  `try:`,
  `    exec(compile(open(sys.argv[1]).read(), "preamble", "exec"), _ns)`,
  `    sys.stdout.write("${READY}\\n")`,
  `except Exception:`,
  `    sys.stdout.write("Python error:\\n" + traceback.format_exc() + "${READY}\\n")`,
  `sys.stdout.flush()`,
  ``,
  `while True:`,
  `    code_lines = []`,
  `    for line in sys.stdin:`,
  `        line = line.rstrip("\\n")`,
  `        if line == "__REPL_EXEC__":`,
  `            break`,
  `        code_lines.append(line)`,
  `    else:`,
  `        break`,
  `    code = "\\n".join(code_lines)`,
  `    _old_stdout = sys.stdout`,
  `    _buf = io.StringIO()`,
  `    sys.stdout = _buf`,
  `    try:`,
  `        exec(compile(code, "<agent>", "exec"), _ns)`,
  `        sys.stdout = _old_stdout`,
  `        output = _buf.getvalue()`,
  `        _old_stdout.write(output)`,
  `        _old_stdout.write("${END_OK}\\n")`,
  `    except Exception:`,
  `        sys.stdout = _old_stdout`,
  `        output = _buf.getvalue()`,
  `        if output:`,
  `            _old_stdout.write(output)`,
  `        _old_stdout.write("Python error:\\n" + traceback.format_exc() + "${END_ERR}\\n")`,
  `    _old_stdout.flush()`,
].join("\n");

export interface REPLResult {
  output: string;
  isError: boolean;
}

export class PythonREPL {
  private proc!: ChildProcess;
  private buffer = "";
  private pending: { resolve: (v: REPLResult) => void } | null = null;
  private wrapperPath: string;
  private ready!: Promise<string>;
  private pythonBin: string;
  private preamblePath: string;
  private crashMessage: string;

  constructor(pythonBin: string, preamblePath: string, crashMessage = "") {
    this.pythonBin = pythonBin;
    this.preamblePath = preamblePath;
    this.crashMessage = crashMessage;
    this.wrapperPath = path.join(os.tmpdir(), `repl_wrapper_${process.pid}_${Date.now()}.py`);
    fs.writeFileSync(this.wrapperPath, WRAPPER_CODE);
    this.spawn();
  }

  private spawn(): void {
    this.buffer = "";
    this.pending = null;
    this.proc = spawn(this.pythonBin, [this.wrapperPath, this.preamblePath], {
      stdio: ["pipe", "pipe", "pipe"],
      env: { ...process.env, PYTHONUNBUFFERED: "1" },
    });
    this.proc.stdout!.setEncoding("utf-8");
    this.proc.stdout!.on("data", (chunk: string) => this.onData(chunk));
    this.proc.stderr!.setEncoding("utf-8");
    this.proc.stderr!.on("data", (chunk: string) => this.onData(chunk));

    this.ready = new Promise((resolve) => {
      const check = () => {
        const idx = this.buffer.indexOf(READY + "\n");
        if (idx >= 0) {
          const preambleOutput = this.buffer.slice(0, idx);
          this.buffer = this.buffer.slice(idx + READY.length + 1);
          resolve(preambleOutput);
        } else {
          setTimeout(check, 50);
        }
      };
      check();
    });
  }

  private respawn(): void {
    try { this.proc.kill(); } catch {}
    this.spawn();
  }

  private onData(chunk: string): void {
    this.buffer += chunk;
    this.tryResolve();
  }

  private tryResolve(): void {
    if (!this.pending) return;
    const okIdx = this.buffer.indexOf(END_OK + "\n");
    const errIdx = this.buffer.indexOf(END_ERR + "\n");
    if (okIdx >= 0) {
      const output = this.buffer.slice(0, okIdx);
      this.buffer = this.buffer.slice(okIdx + END_OK.length + 1);
      const p = this.pending;
      this.pending = null;
      p.resolve({ output: output || "(no output)", isError: false });
    } else if (errIdx >= 0) {
      const output = this.buffer.slice(0, errIdx);
      this.buffer = this.buffer.slice(errIdx + END_ERR.length + 1);
      const p = this.pending;
      this.pending = null;
      p.resolve({ output, isError: true });
    }
  }

  async execute(code: string, timeoutMs = 300000): Promise<REPLResult> {
    await this.ready;
    let respawned = false;
    if (!this.proc.stdin?.writable) {
      this.respawn();
      await this.ready;
      respawned = true;
    }
    const prefix = respawned
      ? `Note: Python session crashed and was restarted. All previous variables are lost -- ${this.crashMessage} Re-load any other data you need.\n\n`
      : "";
    return new Promise((resolve) => {
      const timer = setTimeout(() => {
        this.pending = null;
        this.respawn();
        resolve({
          output: `Python error:\nExecution timed out after ${Math.round(timeoutMs / 60000)} minutes. Session was reset. ${this.crashMessage}`,
          isError: true,
        });
      }, timeoutMs);
      this.pending = {
        resolve: (v) => { clearTimeout(timer); resolve({ output: prefix + v.output, isError: v.isError }); },
      };
      this.proc.stdin!.write(code + "\n__REPL_EXEC__\n");
      this.tryResolve();
    });
  }

  kill(): void {
    try { this.proc.kill(); } catch {}
    try { fs.unlinkSync(this.wrapperPath); } catch {}
  }
}
