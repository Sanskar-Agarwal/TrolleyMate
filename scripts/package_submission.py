"""Build the Canvas submission archive from an exact, committed revision — and prove it runs.

    python scripts/package_submission.py --release v1.0.0
    python scripts/package_submission.py --release v1.0.0 --contribution "Group5 contribution.pdf" --verify

What it does:
  1. refuses uncommitted changes (the archive must be exactly the reviewed commit)
  2. `git archive` of the ref into release/TrolleyMate-Group5-<release>.zip under one top folder
  3. adds RELEASE.txt (release id, commit, build time, how to run) and MANIFEST.sha256
     (a checksum for every file), plus the contribution form if given
  4. checks required files are present (lockfiles, seed data, README, deployment guide)
  5. scans every file for secrets and forbidden paths (.env, keys, databases, node_modules, builds)
  6. writes <zip>.sha256 next to the archive
  7. --verify: extracts the archive into an empty folder and runs scripts/verify_clean.py on it

Owner: Maaz (KAN-30). See docs/SUBMISSION_CHECKLIST.md for the full hand-in steps.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import re
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "release"

REQUIRED = [
    "README.md",
    "docs/DEPLOYMENT.md",
    "docs/SUBMISSION_CHECKLIST.md",
    ".env.example",
    "Dockerfile",
    "docker-compose.yml",
    "backend/requirements.lock",
    "backend/requirements.txt",
    "frontend/package-lock.json",
    "backend/app/seed/catalogue.json",
    "backend/app/seed/recipes.json",
    "scripts/setup.ps1",
    "scripts/setup.sh",
    "scripts/verify_clean.py",
]
FORBIDDEN_PATHS = [
    re.compile(p)
    for p in (
        r"(^|/)\.env$", r"(^|/)\.env\.(?!example$)", r"\.secret_key$", r"\.(db|sqlite3?|db-journal)$",
        r"(^|/)node_modules/", r"(^|/)\.venv/", r"(^|/)frontend/dist/", r"(^|/)__pycache__/", r"\.pem$", r"(^|/)id_rsa",
    )
]
SECRET_PATTERNS = {
    "Anthropic key": re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"),
    "OpenAI-style key": re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9]{32,}"),
    "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "private key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "assigned API key": re.compile(r"""(?im)^\s*(?:LLM_API_KEY|ANTHROPIC_API_KEY|SECRET_KEY)\s*=\s*(?!$|<|change-me|sk-ant-\.\.\.|sk-\.\.\.)\S{12,}"""),
}


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO, check=True, capture_output=True, text=True).stdout.strip()


def fail(msg: str) -> None:
    print(f"FAILED: {msg}")
    sys.exit(1)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--release", required=True, help="release identifier, e.g. v1.0.0 (also the git tag to create)")
    ap.add_argument("--ref", default="HEAD", help="commit or tag to package (default HEAD)")
    ap.add_argument("--contribution", help="path to the completed group contribution statement")
    ap.add_argument("--verify", action="store_true", help="extract the archive and run the clean build on it")
    ap.add_argument("--allow-dirty", action="store_true", help="skip the uncommitted-changes check (dry runs only)")
    args = ap.parse_args()

    if not re.fullmatch(r"v\d+\.\d+\.\d+(-[0-9A-Za-z.]+)?", args.release):
        fail("use a release id like v1.0.0 or v1.0.0-rc1")
    if git("status", "--porcelain") and not args.allow_dirty:
        fail("you have uncommitted changes; commit (and get them reviewed) first so the archive is exactly a commit")
    commit = git("rev-parse", args.ref)
    commit_date = git("show", "-s", "--format=%cI", commit)
    top = f"TrolleyMate-Group5-{args.release}"

    raw = subprocess.run(["git", "archive", "--format=zip", f"--prefix={top}/", commit], cwd=REPO, check=True, capture_output=True).stdout
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        files = {i.filename[len(top) + 1:]: z.read(i) for i in z.infolist() if not i.is_dir()}

    if args.contribution:
        src = Path(args.contribution)
        if not src.is_file():
            fail(f"contribution form not found: {src}")
        files[f"docs/contribution-statement{src.suffix.lower()}"] = src.read_bytes()

    missing = [p for p in REQUIRED if p not in files]
    if missing:
        fail("required files missing from the commit: " + ", ".join(missing))

    problems = [f"forbidden file: {p}" for p in files if any(rx.search(p) for rx in FORBIDDEN_PATHS)]
    for path, data in files.items():
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue  # binary (fonts, images, the PDF form)
        for label, rx in SECRET_PATTERNS.items():
            if rx.search(text):
                problems.append(f"possible {label} in {path}")
    if problems:
        fail("secret/forbidden-content scan:\n  " + "\n  ".join(problems))

    built = datetime.now().astimezone().isoformat(timespec="seconds")
    files["RELEASE.txt"] = (
        f"Trolley Mate — ELEC5620 Group 5\n"
        f"Release:        {args.release}\n"
        f"Commit:         {commit}\n"
        f"Commit date:    {commit_date}\n"
        f"Archive built:  {built}\n"
        f"Contribution:   {'docs/contribution-statement' + Path(args.contribution).suffix.lower() if args.contribution else 'not included'}\n\n"
        "Run it:   docker compose up --build              -> http://localhost:8000\n"
        "      or: scripts/setup.ps1 then scripts/dev.ps1 -> http://localhost:5173 (macOS/Linux: .sh)\n"
        "Check it: python scripts/verify_clean.py --source <this zip>\n"
        "Demo accounts: alex@ / riley@ / sam@ / maya@trolleymate.demo, password demo1234\n"
        "Details: docs/DEPLOYMENT.md. Checksums of every file: MANIFEST.sha256\n"
    ).encode()
    manifest = "".join(f"{hashlib.sha256(data).hexdigest()}  {path}\n" for path, data in sorted(files.items()))
    files["MANIFEST.sha256"] = manifest.encode()

    OUT.mkdir(exist_ok=True)
    zip_path = OUT / f"{top}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for path in sorted(files):
            z.writestr(f"{top}/{path}", files[path])
    digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    (OUT / f"{top}.zip.sha256").write_text(f"{digest}  {zip_path.name}\n", encoding="utf-8")

    size_mb = zip_path.stat().st_size / 1_048_576
    print(f"Release {args.release} = commit {commit[:10]} ({commit_date})")
    print(f"Archive  {zip_path.relative_to(REPO)}  {size_mb:.1f} MB, {len(files)} files")
    print(f"SHA-256  {digest}")
    print("Scan     no secrets or forbidden files; all required files present")

    if args.verify:
        print("Verifying: extracting and running the archive on a clean build ...")
        log = OUT / f"{top}-verify.log"
        code = subprocess.run([sys.executable, str(REPO / "scripts" / "verify_clean.py"), "--source", str(zip_path), "--log", str(log)], check=False).returncode
        if code != 0:
            fail(f"the archive did not build and run cleanly; see {log}")
        print(f"Verified: see {log.relative_to(REPO)}")
    print(f"\nNext: git tag {args.release} {commit[:10]} && git push origin {args.release}, then upload {zip_path.name} to Canvas.")


if __name__ == "__main__":
    main()
