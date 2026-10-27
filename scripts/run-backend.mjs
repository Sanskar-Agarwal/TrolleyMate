// Start the backend dev server with the project venv on Windows, macOS or Linux.
// Used by .claude/launch.json; extra arguments are passed through to uvicorn.
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const backend = join(root, "backend");
const python = process.platform === "win32"
  ? join(backend, ".venv", "Scripts", "python.exe")
  : join(backend, ".venv", "bin", "python");

if (!existsSync(python)) {
  console.error(`No virtual environment at ${python}. Run scripts/setup.${process.platform === "win32" ? "ps1" : "sh"} first.`);
  process.exit(1);
}

const args = ["-m", "uvicorn", "app.main:app", "--port", "8000", "--reload", "--reload-dir", "app", ...process.argv.slice(2)];
const child = spawn(python, args, { cwd: backend, stdio: "inherit" });
child.on("exit", (code) => process.exit(code ?? 0));
for (const signal of ["SIGINT", "SIGTERM"]) process.on(signal, () => child.kill(signal));
