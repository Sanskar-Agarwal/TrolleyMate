# Submission checklist (Stage 2)

Source code is due **1 November 2026, 11:59 PM** (check the Canvas time zone). At the Week 13 demo
we download the zip from Canvas and deploy it on site, so what we upload must build and run on a
machine we have never touched. Owner: Maaz (KAN-30), reviewed by Chester.

## 1. Freeze

- [ ] Every Iteration 3 story is merged to `main` (S05, P05, C05, R05, M05) and CI is green on that commit
- [ ] Demo script dry run passes on `main` ([DEMO_SCRIPT.md](DEMO_SCRIPT.md))
- [ ] Contribution statement completed and agreed by all five members ([CONTRIBUTION_STATEMENT.md](CONTRIBUTION_STATEMENT.md)), exported to PDF
- [ ] Nothing left uncommitted: `git status` is clean

## 2. Build the archive

```bash
git switch main
git pull
python scripts/package_submission.py --release v1.0.0 --contribution "path/to/contribution.pdf" --verify
```

The script refuses uncommitted changes, packages that exact commit, adds `RELEASE.txt` and a
SHA-256 `MANIFEST.sha256`, scans for keys and forbidden files (`.env`, `.secret_key`, databases,
`node_modules`, builds), checks lockfiles, seed data and docs are present, then extracts the zip
into an empty folder and runs the full clean build, tests and startup checks on it.

- [ ] Script ends with `Verified`
- [ ] `release/TrolleyMate-Group5-v1.0.0.zip` and its `.sha256` file exist
- [ ] Zip is well under the Canvas size limit (about 0.3 MB; no dependencies or builds are included)

## 3. Record the release

```bash
git tag v1.0.0 <commit printed by the script>
git push origin v1.0.0
```

- [ ] Tag pushed; GitHub release created with the zip and checksum attached
- [ ] Release id, commit and checksum pasted into the Jira ticket (KAN-30) and the sprint review notes

## 4. Upload early, then check what Canvas gives back

- [ ] Upload the zip to Canvas by **30 October** (a day of slack before the deadline)
- [ ] Download it again from Canvas on a different machine and compare the checksum:
  - Windows: `certutil -hashfile TrolleyMate-Group5-v1.0.0.zip SHA256`
  - macOS/Linux: `shasum -a 256 TrolleyMate-Group5-v1.0.0.zip`
- [ ] Run `python scripts/verify_clean.py --source TrolleyMate-Group5-v1.0.0.zip` on the downloaded copy
- [ ] Contribution statement attached as the brief requires

## 5. Demo day (Week 13)

- [ ] Laptop has Python 3.11+, Node 20+ (and Docker, if we use it) installed and tested the day before
- [ ] Download from Canvas, unzip, then `docker compose up --build` or `scripts/setup.*` + `scripts/dev.*`
- [ ] If the campus VPN or AI key isn't available, run in offline agent mode and say so; the badge
      shows it ([DEPLOYMENT.md](DEPLOYMENT.md#which-ai-mode-is-running))
- [ ] Recovery steps to hand: [DEPLOYMENT.md](DEPLOYMENT.md#recovery)
