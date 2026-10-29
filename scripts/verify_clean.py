"""Rebuild and run Trolley Mate from a clean copy of the source, the way the Week 13 demo will.

    python scripts/verify_clean.py                      # clean copy of the current commit (git archive HEAD)
    python scripts/verify_clean.py --source release.zip # verify an existing submission archive
    python scripts/verify_clean.py --log docs/evidence/clean-deploy.log

Steps: stage the source in an empty temp folder -> fresh Python venv from the pinned lockfile ->
pip check -> backend tests (offline mock) -> npm ci, frontend tests and production build ->
start the server with no AI key and check health, the built UI, demo sign-in and a full basket
build -> start it again with an unreachable AI provider and check the fallback is labelled.
Use Python 3.12 and Node 20.19+ (20.x), 22.12+ (22.x), or 24+; git is needed for the
default source. Initial dependency installation needs registry access. See docs/DEPLOYMENT.md
for archive preparation. Owner: Maaz (KAN-29).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WINDOWS = os.name == "nt"
LOG: list[str] = []
ANSI = re.compile(r"\x1b\[[0-9;]*m")  # terminal colour codes from npm/vite output


def say(msg: str) -> None:
    line = f"[{datetime.now():%H:%M:%S}] {msg}"
    print(line, flush=True)
    LOG.append(line)


def run(cmd: list[str], cwd: Path, env: dict | None = None, tail: int = 4) -> str:
    started = time.perf_counter()
    proc = subprocess.run(cmd, check=False, cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", shell=WINDOWS and cmd[0] in ("npm", "npx"))
    out = ANSI.sub("", proc.stdout + proc.stderr).strip()
    took = time.perf_counter() - started
    if proc.returncode != 0:
        say(f"FAILED ({took:.0f}s): {' '.join(cmd)}\n{out[-3000:]}")
        raise SystemExit(1)
    summary = " | ".join(line.strip() for line in out.splitlines()[-tail:] if line.strip())
    say(f"ok ({took:.0f}s): {' '.join(cmd)}" + (f"\n    {summary}" if summary else ""))
    return out


def stage(source: str | None, into: Path) -> Path:
    if source and source.endswith(".zip"):
        with zipfile.ZipFile(source) as z:
            z.extractall(into)
        roots = [p for p in into.iterdir() if p.is_dir()]
        root = roots[0] if len(roots) == 1 and not (into / "backend").exists() else into
        say(f"Staged archive {source} -> {root}")
        return root
    ref = source or "HEAD"
    archive = into / "src.zip"
    run(["git", "archive", "--format=zip", "-o", str(archive), ref], cwd=REPO)
    with zipfile.ZipFile(archive) as z:
        z.extractall(into / "src")
    archive.unlink()
    say(f"Staged git {ref} ({run(['git', 'rev-parse', '--short', ref], cwd=REPO).strip()}) -> {into / 'src'}")
    return into / "src"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def http(method: str, url: str, body: dict | None = None, token: str | None = None) -> tuple[int, str]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def serve(py: Path, backend: Path, env: dict) -> tuple[subprocess.Popen, str]:
    port = free_port()
    proc = subprocess.Popen([str(py), "-m", "uvicorn", "app.main:app", "--port", str(port)], cwd=backend, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    base = f"http://127.0.0.1:{port}"
    for _ in range(60):
        try:
            if http("GET", f"{base}/api/health")[0] == 200:
                return proc, base
        except OSError:
            pass
        time.sleep(1)
    proc.kill()
    say("FAILED: server did not become healthy\n" + (proc.stdout.read() if proc.stdout else ""))
    raise SystemExit(1)


def journey(base: str) -> dict:
    """Sign in as a demo shopper and build a basket end to end through the API."""
    status, body = http("POST", f"{base}/api/auth/login", {"email": "riley@trolleymate.demo", "password": "demo1234"})
    assert status == 200, f"demo sign-in failed: {status} {body[:200]}"
    token = json.loads(body)["token"]
    sid = json.loads(http("POST", f"{base}/api/sessions", {}, token)[1])["session"]["id"]
    intake = json.loads(http("POST", f"{base}/api/sessions/{sid}/requests", {"text": "$70 for the week, two meals a day for myself"}, token)[1])
    rid = intake["intake"]["request_id"]
    status, body = http("POST", f"{base}/api/requests/{rid}/confirm", {}, token)
    assert status == 200, f"confirm failed: {body[:200]}"
    built = json.loads(http("POST", f"{base}/api/sessions/{sid}/basket", {"goal": "balanced"}, token)[1])
    assert built["status"] == "ok", f"basket build failed: {str(built)[:300]}"
    llm = json.loads(http("GET", f"{base}/api/system/llm")[1])
    return {"basket_total": built["basket"]["total"], "items": len(built["basket"]["items"]),
            "trace_steps": len(built["trace"]), "llm_steps": [t for t in built["trace"] if t["llm"]], "llm": llm}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--source", help="a .zip archive or git ref (default: HEAD)")
    ap.add_argument("--log", help="write the run log to this file")
    ap.add_argument("--keep", action="store_true", help="keep the temporary build folder")
    args = ap.parse_args()

    work = Path(tempfile.mkdtemp(prefix="trolleymate-clean-"))
    say(f"Clean verification on {sys.platform}, Python {sys.version.split()[0]}, work dir {work}")
    try:
        root = stage(args.source, work)
        backend, frontend = root / "backend", root / "frontend"
        for unwanted in (".env", "backend/.secret_key", "backend/trolleymate.db", "frontend/node_modules", "frontend/dist"):
            if (root / unwanted).exists():
                say(f"FAILED: source contains {unwanted}; it must be built or generated, not shipped")
                raise SystemExit(1)

        run([sys.executable, "-m", "venv", ".venv"], cwd=backend)
        py = backend / ".venv" / ("Scripts" if WINDOWS else "bin") / ("python.exe" if WINDOWS else "python")
        run([str(py), "-m", "pip", "install", "-q", "--upgrade", "pip"], cwd=backend)
        run([str(py), "-m", "pip", "install", "-q", "--no-deps", "-r", "requirements.lock"], cwd=backend)
        run([str(py), "-m", "pip", "check"], cwd=backend)
        run([str(py), "-m", "pip", "install", "-q", "-r", "requirements-dev.txt"], cwd=backend)

        env = {**os.environ, "LLM_PROVIDER": "mock", "PYTHONUTF8": "1"}
        for key in ("LLM_API_KEY", "ANTHROPIC_API_KEY", "LLM_BASE_URL", "LLM_MODEL", "SECRET_KEY", "DATABASE_URL"):
            env.pop(key, None)
        run([str(py), "-m", "pytest", "-q", "-p", "no:cacheprovider"], cwd=backend, env=env)

        run(["npm", "ci", "--no-audit", "--no-fund"], cwd=frontend)
        run(["npm", "test"], cwd=frontend, tail=6)
        run(["npm", "run", "build"], cwd=frontend)

        # 1) No AI key at all: the default for a fresh machine.
        env_offline = {**env, "DATABASE_URL": f"sqlite:///{(work / 'offline.db').as_posix()}"}
        proc, base = serve(py, backend, env_offline)
        try:
            status, page = http("GET", f"{base}/")
            assert status == 200 and "<div id=\"root\">" in page, "built UI was not served"
            result = journey(base)
            assert result["llm"]["mode"] == "offline", result["llm"]
            say(f"ok: no AI key -> {result['llm']['mode_label']}; basket ${result['basket_total']:.2f}, "
                f"{result['items']} items, {result['trace_steps']} agent steps; UI served at /")
        finally:
            proc.terminate()
            proc.wait(timeout=20)

        # 2) A configured provider that can't be reached (VPN down, network out).
        env_down = {**env, "LLM_PROVIDER": "openai_compatible", "LLM_BASE_URL": "http://127.0.0.1:9/v1",
                    "LLM_MODEL": "campus-qwen", "LLM_API_KEY": "unused", "LLM_TIMEOUT_S": "2",
                    "DATABASE_URL": f"sqlite:///{(work / 'down.db').as_posix()}"}
        proc, base = serve(py, backend, env_down)
        try:
            result = journey(base)
            steps = result["llm_steps"]
            assert steps and all(t["fell_back"] for t in steps), steps
            assert result["llm"]["mode"] == "degraded", result["llm"]
            say(f"ok: AI provider unreachable -> {result['llm']['mode_label']}; basket still built "
                f"(${result['basket_total']:.2f}) with every AI step ({len(steps)}) flagged as a fallback")
        finally:
            proc.terminate()
            proc.wait(timeout=20)

        say("PASSED: clean build, tests, startup, offline mode and network-failure fallback all verified")
    finally:
        if args.log:
            Path(args.log).parent.mkdir(parents=True, exist_ok=True)
            Path(args.log).write_text("\n".join(LOG) + "\n", encoding="utf-8")
        if args.keep:
            say(f"Kept {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
