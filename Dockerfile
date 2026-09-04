# syntax=docker/dockerfile:1
#
# Drift Detector — the headless, deterministic SCAN runner.
#
# NO AI lives in this image: it carries ONLY the agent/ Python package and the pinned
# ast-grep engine — no promptfiles (commands/), no LLM client. This is the container CI
# pulls (by digest) to run `drift run | verify | deliver`. The AI-assisted Learn loop is a
# SEPARATE thing (the Claude Code plugin), never packaged here. See docs/CONTAINER.md.
#
# Determinism (CLAUDE.md principle 3): the engine is version-pinned AND sha256-verified, and
# there is NO "fall back to latest" — a mismatch or a failed fetch FAILS the build. Bump the
# version + sha only after re-verifying the ruleset. The IMAGE itself is then pinned by
# DIGEST in the consumer's .gitlab-ci.yml, so every CI run uses byte-identical bits.

# ---- stage 1: fetch + verify the pinned scan engine ------------------------------------
FROM debian:12-slim AS engine
# Keep AST_GREP_VERSION identical to bin/drift-scan's DRIFT_AST_GREP_VERSION default;
# tests/test_container.py fails the build's CI if the two ever drift.
ARG AST_GREP_VERSION=0.44.1
# sha256 of the EXTRACTED linux-x86_64 ast-grep binary (what actually runs), not the zip.
ARG AST_GREP_SHA256=d2716ddc04f67af933ebaaab39404a184d4fae84e43402fe9b3232b1cdc83728
ARG AST_GREP_ASSET=app-x86_64-unknown-linux-gnu.zip
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends curl unzip ca-certificates; \
    url="https://github.com/ast-grep/ast-grep/releases/download/${AST_GREP_VERSION}/${AST_GREP_ASSET}"; \
    curl -fsSL -o /tmp/sg.zip "$url"; \
    unzip -qo /tmp/sg.zip -d /tmp; \
    echo "${AST_GREP_SHA256}  /tmp/ast-grep" | sha256sum -c -; \
    install -m 0755 /tmp/ast-grep /usr/local/bin/ast-grep; \
    /usr/local/bin/ast-grep --version

# ---- stage 1b: fetch + verify the secret-detection engine (gitleaks) -------------------
# OPTIONAL at runtime (agent.lib.secrets_scan degrades a missing gitleaks to UNKNOWN, not
# a failed scan) — but not optional IN THIS IMAGE: a controlled, reproducible build has no
# "user chose not to install it" case, so this stage fails the build exactly like ast-grep's
# does, rather than the best-effort degrade bin/drift-scan uses for an arbitrary dev machine.
FROM debian:12-slim AS secrets
# Keep GITLEAKS_VERSION identical to bin/drift-scan's DRIFT_GITLEAKS_VERSION default;
# tests/test_container.py fails the build's CI if the two ever drift.
ARG GITLEAKS_VERSION=8.30.1
# sha256 of the linux-x64 release tarball, independently re-verified against the
# downloaded bytes when this stage was written (not copied blind from gitleaks' own
# checksums file, which is fetched from the same host as the binary it attests).
ARG GITLEAKS_SHA256=551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends curl ca-certificates; \
    asset="gitleaks_${GITLEAKS_VERSION}_linux_x64.tar.gz"; \
    url="https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/${asset}"; \
    curl -fsSL -o /tmp/gitleaks.tar.gz "$url"; \
    echo "${GITLEAKS_SHA256}  /tmp/gitleaks.tar.gz" | sha256sum -c -; \
    tar -xzf /tmp/gitleaks.tar.gz -C /tmp gitleaks; \
    install -m 0755 /tmp/gitleaks /usr/local/bin/gitleaks; \
    /usr/local/bin/gitleaks version

# ---- stage 2: the runtime image --------------------------------------------------------
FROM python:3.12-slim
LABEL org.opencontainers.image.title="drift-detector-scan" \
      org.opencontainers.image.description="Deterministic, zero-AI Drift Detector scan runner" \
      org.opencontainers.image.source="https://github.com/TOPSinfo/drift-detector-scan"

# git: the scanner reads git metadata and `run --pull` clones the fleet.
# ca-certificates: HTTPS to the GitLab instance, OSV.dev and endoflife.date.
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends git ca-certificates; \
    rm -rf /var/lib/apt/lists/*

# runtime is stdlib + PyYAML only (dropping semgrep took the install 386MB -> 90MB)
COPY requirements-plugin.txt /tmp/requirements-plugin.txt
RUN pip install --no-cache-dir -r /tmp/requirements-plugin.txt

COPY --from=engine /usr/local/bin/ast-grep /usr/local/bin/ast-grep
COPY --from=secrets /usr/local/bin/gitleaks /usr/local/bin/gitleaks
# ONLY the agent package. Deliberately NOT commands/ — there is no AI path in the image.
COPY agent/ /app/agent/

# a `drift` command so `docker run IMG run …` (via ENTRYPOINT) AND a GitLab CI
# `script: drift run …` (which overrides the entrypoint) both work, from any working
# directory — PYTHONPATH makes agent importable regardless of cwd.
RUN printf '#!/bin/sh\nexec python -m agent.cli "$@"\n' > /usr/local/bin/drift; \
    chmod +x /usr/local/bin/drift

ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1
WORKDIR /work
ENTRYPOINT ["drift"]
CMD ["--help"]
