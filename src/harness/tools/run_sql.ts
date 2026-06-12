/**
 * `run_sql(sql: str) -> str` — SQL execution tool for LiveSQLBench tasks.
 *
 * Takes a raw SQL query string, executes it against the task's SQLite database
 * (DB_PATH is set in the preamble by buildPreamble when task.db_path is present),
 * and returns results as a JSON array of row objects.
 *
 * Uses the same PythonREPL as run_python internally — no new infrastructure.
 * The key difference: the model only sees a SQL-in / JSON-out interface.
 * It cannot call run_python, so it cannot drift into pandas data manipulation.
 *
 * P1 Tier-B verifier: BEFORE executing, we parse the SQL with `sqlglot` (run via
 * the persistent Python REPL). If the parse fails, we return
 * `[VERIFY: FAIL sqlglot_parse] <error>` and SKIP execution — the syntax is
 * broken and SQLite would just produce a less-useful error. If the parse
 * succeeds the SQL is executed normally.
 *
 * Preamble must have been built with task.db_path set (injects DB_PATH + run_sql helper).
 */
import { Type } from "@sinclair/typebox";
import type { AgentToolResult } from "@mariozechner/pi-agent-core";
import type { PythonREPL } from "../services/python_repl.js";
import type { ToolDefinition } from "./index.js";

export function makeRunSqlTool(repl: PythonREPL): ToolDefinition {
  return {
    name: "run_sql",
    label: "Run SQL",
    description:
      "Execute a SQL query against this task's SQLite database. " +
      "Returns a JSON array of row objects. " +
      "Use it to: (1) verify intermediate CTE outputs, (2) test joins, " +
      "(3) run your final query and check the result shape. " +
      "You may call this multiple times.",
    parameters: Type.Object({
      sql: Type.String({ description: "A complete SQL statement to execute." }),
    }),
    execute: async (_toolCallId: string, params: any): Promise<AgentToolResult<unknown>> => {
      const sql = (params.sql as string).trim();
      // Tier B: pre-flight parse via sqlglot (in the REPL). The REPL is a
      // persistent process so sqlglot stays imported across calls.
      // If sqlglot is not installed, we silently fall through to the executor —
      // verifier failures must NEVER block the executor.
      const code = `
import json as _json
_p1_sql = ${JSON.stringify(sql)}
_p1_sql_report = []
try:
    import sqlglot as _p1_sqlglot
    try:
        _p1_sqlglot.parse_one(_p1_sql, read="sqlite")
        _p1_parse_ok = True
    except Exception as _p1_e:
        _p1_parse_ok = False
        _p1_sql_report.append(f"[VERIFY: FAIL sqlglot_parse] {type(_p1_e).__name__}: {str(_p1_e)[:300]}")
except ImportError:
    _p1_parse_ok = True  # sqlglot unavailable; skip pre-flight check

if _p1_parse_ok:
    try:
        _rows = run_sql(_p1_sql)
        print(_json.dumps(_rows[:100]))  # cap at 100 rows
        if _p1_sql_report:
            print("\\n" + "\\n".join(_p1_sql_report))
    except Exception as _p1_run_e:
        # Re-raise so the harness sees Python error + stack trace (matches prior behaviour).
        raise
else:
    # Skip execution; surface the parse failure tag only.
    print("\\n".join(_p1_sql_report))

for _p1_n in ("_json","_p1_sql","_p1_sql_report","_p1_sqlglot","_p1_parse_ok","_p1_e","_p1_run_e","_p1_n"):
    globals().pop(_p1_n, None)
`.trim();
      const { output } = await repl.execute(code);
      return { content: [{ type: "text", text: output }], details: {} };
    },
  };
}
