# Release rehearsal: v1.0.0-rc1 (KAN-30)

A dry run of the submission process on 29 October, before Iteration 3 stories were merged. The
final `v1.0.0` archive must be rebuilt the same way from `main` once S05, P05, C05, R05 and M05
are in (see [SUBMISSION_CHECKLIST.md](../SUBMISSION_CHECKLIST.md)).

| | |
|---|---|
| Release id | `v1.0.0-rc1` (not tagged: rehearsal only) |
| Commit | `bd0081577f` (2026-10-29 14:48 +11:00) |
| Archive | `TrolleyMate-Group5-v1.0.0-rc1.zip`, 0.3 MB, 211 files incl. `RELEASE.txt` and `MANIFEST.sha256` |
| SHA-256 | `b383c343e309e6d237563d27a6c097036c1eb154e1ddb8dfc26f6db117d2fe51` |
| Secret scan | no secrets or forbidden files; lockfiles, seed data and docs present |
| Negative check | a planted `.env` and a fake `sk-ant-` key in a throwaway worktree were both rejected |
| Clean run of the extracted archive | **passed**: pinned install + `pip check`, all backend and frontend tests, production build, startup with no AI key (offline mode labelled), startup with an unreachable provider (basket built, AI step flagged as fallback) |

Command: `python scripts/package_submission.py --release v1.0.0-rc1 --verify`.
Full log: [release-v1.0.0-rc1-verify.log](release-v1.0.0-rc1-verify.log).
