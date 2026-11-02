# CI and container releases

The [CI workflow](../.github/workflows/ci.yml) checks pull requests and pushes to `main`.
Successful `main` runs publish a Docker image to GitHub Container Registry (GHCR). The
workflow does not provision a server or deploy a running application.

An image is available only after its **publish** job succeeds. As of 29 October 2026,
main commit `947a59c` passed all four jobs, including publishing, in
[run 40806441408](https://github.com/rkn321/ELEC5620-Group5-TrolleyMate/actions/runs/40806441408).
The [verification summary](../README.md#verification) records the corresponding 416 backend
tests, 57 frontend tests and separate local Docker checks. For a newer commit, check the
[workflow runs](https://github.com/rkn321/ELEC5620-Group5-TrolleyMate/actions/workflows/ci.yml)
and the repository's **Packages** panel before using its tag. Dated evidence describes the
revision it names; a passing earlier run does not validate later changes.

## What runs

| Stage | Checks | When |
|---|---|---|
| Backend | Python 3.12, `requirements-dev.txt` (including the runtime lockfile), `ruff check app tests`, `pytest` with `LLM_PROVIDER=mock` | Pull requests and pushes to `main` |
| Frontend | Node 22, `npm ci`, React component tests (`npm test`), TypeScript and production build (`npm run build`) | Pull requests and pushes to `main` |
| Docker | Build the single-container image; check API health, compiled frontend assets, and demo login with an authenticated API request | After both test jobs pass |
| Publish | Load the tested image and push the release tags to GHCR | Successful pushes to `main` only |

The Docker job transfers the smoke-tested image to the publish job using a GitHub Actions
artifact retained for one day. The publish job verifies the loaded image ID before publishing;
it does not rebuild the image. If the commit tag already exists, it reuses the original
published image as described below.

The workflow's container smoke covers health, compiled JS/CSS, login and `/api/auth/me`.
The fuller local Docker checks (registration, cancellation, ownership and dietary regressions)
are recorded separately from that workflow. Runtime dependency installation and `pip check`
also run inside the Dockerfile build.

Pull requests never log in to GHCR or publish images. A branch push without an associated
pull-request event does not trigger this workflow unless the branch is `main`.

CI uses the offline LLM mock and requires no model credentials. Publishing uses GitHub's
automatic `GITHUB_TOKEN`; `packages: write` is granted only to the publish job. No custom
registry password or hosting secret is required. Passing CI does not test a hosted model's
availability, credentials or response quality. Failed configured-model calls can use the
labelled mock fallback; uncertain ingredient checks remain withheld for review, as described
in [DEPLOYMENT.md](DEPLOYMENT.md#which-ai-mode-is-running).

## Image names and versions

The image is `ghcr.io/rkn321/elec5620-group5-trolleymate` with two tag forms:

- `latest`: the current published main-branch image, convenient for trying the demo. A run
  updates it only if its commit is still the head of `main` when the publisher checks.
- `sha-<full-commit-hash>`: the image associated with a specific 40-character commit hash.
  Use a published SHA tag when recording a demo version or selecting a rollback version.

Reruns preserve an existing SHA tag and reuse that image instead of replacing it with a new
build. They can retry a failed `latest` update using the existing SHA image. Registry or
authentication errors stop publication; they are not treated as an absent tag. If the tested
image artifact has expired, use **Re-run all jobs** in GitHub Actions to recreate it before
retrying publication.

The workflow builds on the standard x64 `ubuntu-latest` runner, so its published image is
`linux/amd64`; it does not publish a multi-platform image. The separate local verification ran
on `linux/arm64`. On Apple Silicon or another ARM64 machine, the
commands below request amd64 emulation explicitly. Docker Desktop normally provides this;
other Docker installations need compatible emulation. To build for your local platform,
use `docker compose up --build` from the repository instead.

## Pull and run locally

Docker must be installed and running. Authenticate first if the package is private (see
below), then run:

```bash
docker pull --platform linux/amd64 ghcr.io/rkn321/elec5620-group5-trolleymate:latest
docker run --detach --name trolleymate --platform linux/amd64 \
  --publish 127.0.0.1:8000:8000 \
  --env LLM_PROVIDER=mock \
  --volume trolleymate-data:/data \
  ghcr.io/rkn321/elec5620-group5-trolleymate:latest
```

Open [the app](http://localhost:8000) or [API docs](http://localhost:8000/docs). Demo accounts
and passwords are listed in the [README](../README.md#quick-start). The examples bind port
8000 to your machine's loopback interface and seed demo data on the first start. The named
volume stores the SQLite database at `/data/trolleymate.db` across container replacements.
It is separate from the project-prefixed volume created by the default Compose command.

Existing volumes keep their users and catalogue: startup seeding does not overwrite them.
The automatically generated signing key lives in the container, so replacement requires
signing in again unless you provide a persistent `SECRET_KEY` at runtime. The default command
runs one server process; the basket cancellation registry is not shared across worker processes.

To inspect the running container:

```bash
curl --fail http://localhost:8000/api/health
docker logs trolleymate
```

Stop an existing local development server or Compose container first if it already uses
port 8000. A previous container named `trolleymate` must also be removed before reusing
that name; the update steps below show how. To keep another app running on port 8000, choose
a different host port, for example `--publish 127.0.0.1:8028:8000`, and open that port instead.

## Package access

A newly published package may be private. The package owner can manage access and
visibility in GitHub's package settings. Public GHCR images support anonymous pulls;
private images require an account with package access and a personal access token
**(classic)** with `read:packages`. Enter that token at Docker's password prompt:

```bash
docker login ghcr.io --username YOUR_GITHUB_USERNAME
```

Keep tokens out of source files, command arguments, and commits. If an organisation requires
SSO, authorise the token for that organisation. GitHub documents these requirements in
[Working with the Container registry](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry)
and [package permissions](https://docs.github.com/en/packages/learn-github-packages/about-permissions-for-github-packages).

If publishing reports a package-permission error, the owner should check that this repository
has Actions write access to the package. If pulling fails, first confirm that the selected
tag was published, then check the package's visibility and your read access.

## Update or roll back

Choose a SHA tag from a successful publish run. Replace the placeholder below with that
commit's full hash. Pull it before stopping the current container so a missing tag or
authentication problem does not interrupt the running demo.

```bash
docker pull --platform linux/amd64 ghcr.io/rkn321/elec5620-group5-trolleymate:sha-FULL_COMMIT_HASH
docker stop trolleymate
docker rm trolleymate
docker run --detach --name trolleymate --platform linux/amd64 \
  --publish 127.0.0.1:8000:8000 \
  --env LLM_PROVIDER=mock \
  --volume trolleymate-data:/data \
  ghcr.io/rkn321/elec5620-group5-trolleymate:sha-FULL_COMMIT_HASH
```

Use the same steps with an earlier published SHA tag to roll back the application. Keep the
named volume to preserve data. This changes the application image, not the database; check
schema compatibility and back up the data before switching between versions with database
changes. No migration scripts are provided. A data reset deletes accounts, household profiles,
preferences, baskets, reviews and audit history; it is not a routine image-update step. See
[Resetting demo data](DEPLOYMENT.md#resetting-demo-data) for disposable demo databases.

## Build without GHCR

From the repository root:

```bash
docker compose up --build
```

This builds from the local source and does not require a published GHCR image or registry
login. It still needs access to base images and dependency registries during the build.
Compose reads an optional local `.env`; without one, the default LLM provider is `mock`.
An existing `.env` can select a different provider or database. See
[DEPLOYMENT.md](DEPLOYMENT.md#configuration) for configuration and fallback behavior.

The optional [Render blueprint](../render.yaml) is a separate hosting configuration. Its
`autoDeploy` setting applies only after a Render service has been connected; the GitHub Actions
workflow does not trigger or wait for it. The blueprint uses an ephemeral SQLite database,
so do not rely on it for data that must survive a service replacement. Set `LLM_PROVIDER=mock`
explicitly for an offline hosted demo.
