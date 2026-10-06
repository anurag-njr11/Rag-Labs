// PreToolUse (Bash|PowerShell): project rule — browser tests run in a visible
// browser the user can watch, never headless.
const input = JSON.parse(await readStdin());
const command = input.tool_input?.command ?? "";

const headless =
  /headless\s*[:=]\s*(true|True|1)\b/.test(command) ||   // headless=True, headless: true
  /--headless(?!\s*=\s*(false|0)\b)/.test(command);      // --headless, --headless=new

if (headless) {
  console.log(JSON.stringify({
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "deny",
      permissionDecisionReason:
        "This project runs browser tests headed. Use headless: false (Playwright) " +
        "or the claude-in-chrome skill so the user can watch.",
    },
  }));
}
process.exit(0);

async function readStdin() {
  let data = "";
  for await (const chunk of process.stdin) data += chunk;
  return data;
}
