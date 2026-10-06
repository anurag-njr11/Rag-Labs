// PostToolUse (Edit|Write): check the file Claude just changed.
//   frontend/**/*.ts(x) -> oxlint on that file (errors only)
//   backend/**/*.py     -> byte-compile with the backend venv (catches syntax errors)
// A failure exits 2, so Claude sees the output and fixes it in the same turn.
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";

const input = JSON.parse(await readStdin());
const file = input.tool_input?.file_path;
if (!file) process.exit(0);

const root = process.env.CLAUDE_PROJECT_DIR || input.cwd;
const abs = path.resolve(root, file);
const rel = path.relative(root, abs).split(path.sep).join("/");
const win = process.platform === "win32";

let result;
if (/^frontend\/src\/.*\.(ts|tsx)$/.test(rel)) {
  const frontend = path.join(root, "frontend");
  const oxlint = path.join(frontend, "node_modules", ".bin", win ? "oxlint.cmd" : "oxlint");
  if (!existsSync(oxlint)) process.exit(0);
  result = run(oxlint, ["--quiet", abs], frontend);
} else if (/^backend\/.*\.py$/.test(rel) && !rel.includes("/.venv/")) {
  const venv = path.join(root, "backend", ".venv", win ? "Scripts/python.exe" : "bin/python");
  result = run(existsSync(venv) ? venv : "python", ["-m", "py_compile", abs], root);
} else {
  process.exit(0);
}

if (result.status !== 0) {
  process.stderr.write(`Check failed for ${rel}:\n${result.output.trim()}\n`);
  process.exit(2);
}
process.exit(0);

function run(cmd, args, cwd) {
  // .cmd shims need a shell on Windows; quote every part because the repo path has a space.
  const r = win && cmd.endsWith(".cmd")
    ? spawnSync([cmd, ...args].map((a) => `"${a}"`).join(" "), { cwd, shell: true, encoding: "utf8" })
    : spawnSync(cmd, args, { cwd, encoding: "utf8" });
  return { status: r.status ?? 1, output: `${r.stdout ?? ""}${r.stderr ?? ""}${r.error ?? ""}` };
}

async function readStdin() {
  let data = "";
  for await (const chunk of process.stdin) data += chunk;
  return data;
}
