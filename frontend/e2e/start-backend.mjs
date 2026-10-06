// Starts EmneKlar for end-to-end tests: a fake Canvas, a throw-away data folder, secrets in memory
// and a fixed local login token. The backend serves the built frontend (run `npm run build` first).
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repo = join(here, "..", "..");
const candidates = [
  process.env.EMNEKLAR_PYTHON,
  join(repo, "backend", ".venv", "Scripts", "python.exe"),
  join(repo, "backend", ".venv", "bin", "python"),
  "python3",
  "python",
].filter(Boolean);
const python = candidates.find((p) => (p.includes("/") || p.includes("\\") ? existsSync(p) : true));

const port = process.env.EMNEKLAR_E2E_PORT ?? "8768";
const canvasPort = process.env.EMNEKLAR_E2E_CANVAS_PORT ?? "8792";
const child = spawn(python, ["backend/tests/fakes/dev_server.py", "--port", port, "--canvas-port", canvasPort, "--configured"], {
  cwd: repo,
  stdio: "inherit",
  env: { ...process.env, PYTHONUTF8: "1" },
});
const stop = () => child.kill();
process.on("SIGINT", stop);
process.on("SIGTERM", stop);
process.on("exit", stop);
child.on("exit", (code) => process.exit(code ?? 0));
