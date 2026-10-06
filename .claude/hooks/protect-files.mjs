// PreToolUse (Edit|Write): stop Claude from hand-editing files it shouldn't touch.
// Blocks secrets, runtime data, installed dependencies and lock files.
import path from "node:path";

const input = JSON.parse(await readStdin());
const file = input.tool_input?.file_path;
if (!file) process.exit(0);

const root = process.env.CLAUDE_PROJECT_DIR || input.cwd;
const rel = path.relative(root, path.resolve(root, file)).split(path.sep).join("/");

const rules = [
  [/(^|\/)\.env(\.|$)/, "it holds API keys; edit it yourself"],
  [/^data\//, "it is runtime data written by the backend (uploads, SQLite, indexes)"],
  [/(^|\/)\.venv\//, "it is the installed Python environment; change dependencies with uv"],
  [/(^|\/)node_modules\//, "it is installed packages; change dependencies with npm"],
  [/(^|\/)(package-lock\.json|uv\.lock)$/, "lock files are written by npm / uv, not by hand"],
];

for (const [pattern, why] of rules) {
  if (pattern.test(rel)) {
    deny(`Blocked edit to ${rel}: ${why}.`);
  }
}
process.exit(0);

function deny(reason) {
  console.log(JSON.stringify({
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "deny",
      permissionDecisionReason: reason,
    },
  }));
  process.exit(0);
}

async function readStdin() {
  let data = "";
  for await (const chunk of process.stdin) data += chunk;
  return data;
}
