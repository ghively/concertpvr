# jules.md — entry point for the next agent

Drop-in instructions for the next agent picking up concertpvr work. Read this top-to-bottom before touching anything.

---

## Repo state

- **Tag:** `v0.3.2` (pushed to `origin/main`)
- **Branch:** `main`
- **Backend tests:** 286 passing, ruff/format/mypy clean
- **Frontend:** typecheck + build clean
- **Smokes:** docker + e2e green

The v0.3.2 release is shipped. There is **no active work in progress** — clean tree.

---

## Next phase: v0.3.3 — VOD bug sweep + Most viewed sort

The full implementation plan is in:

**`docs/superpowers/plans/2026-04-27-v0.3.3-vod-bug-sweep.md`**

That file is self-contained: 16 numbered tasks across 5 waves, with concrete code examples for the trickier ones, commit messages, test expectations, and a manual UI walk-through at the end. Do not re-derive the design — the architectural decisions (slow-refresh opt-in for view counts, no like counts, cancel-for-queued-only, per-watcher comments toggle on URL paste) are already chosen and documented in the plan's preamble.

### How to execute the plan

The plan uses the `superpowers:subagent-driven-development` pattern. Each task has checkbox steps. Mark each `- [ ]` as `- [x]` as you complete them, but **do not** edit the plan to record decisions you made — open a new commit to update specs/CHANGELOG/docs instead. The plan file is the source of truth for *what was planned*; the commits are the source of truth for *what shipped*.

Recommended cadence:
1. Read the entire plan once before starting. Note the cross-cutting guardrails.
2. Execute task by task in order. Each task ends with a commit; do not batch.
3. After each wave: run the audit checks listed in the plan.
4. After Wave 5: tag `v0.3.3` and push.

If a task hits an unexpected obstacle, **stop and surface it to the user** rather than improvising. The plan was written from a real audit; deviations should be deliberate, not accidental.

---

## Before you start (environment + sanity)

### 1. Confirm clean tree

```bash
git status        # working tree should be clean (only .claude/settings.local.json drift is fine)
git log --oneline -5
# expect: ... 'docs: v0.3.3 implementation plan ...' as recent
```

### 2. Confirm tooling

```bash
./.venv/Scripts/python.exe --version    # 3.12.x expected
./.venv/Scripts/python.exe -m pytest -q # should pass: 286 tests
cd frontend && npm run typecheck && cd ..
```

If any of these fail, **diagnose first** — do not start the plan on top of a broken baseline.

### 3. Confirm Docker is reachable (needed for Wave 5 smokes)

```bash
docker version
docker compose -f docker-compose.dev.yml build
```

---

## Cross-cutting guardrails (consolidated)

These apply to every task. The plan repeats them — they're here for quick reference.

1. **Live recording path is sacred.** No edits to `recorder.py`, `pool.py`, `buffer.py`, `recording_starter.py`, `LiveProgressBar.tsx`. v0.3.3 touches VOD + backlog only.
2. **No new database tables. No migrations.** v0.3.3 uses existing columns.
3. **`Recording.status="failed"` stays reserved (live-only, not currently emitted).** Don't add code that emits it.
4. **No mypy/ruff strictness relaxation. No test rewriting that hides spec.**
5. **All existing tests must stay green.** Test count monotonically increases.
6. **Backlog browse never auto-downloads.** The guardrail test in `tests/test_backlog_cache.py` enforces this — re-verify after any backlog work.
7. **Auto-pull from channel subscriptions stays opt-in.** v0.3.2's `watch_vod_uploads=false` default holds.
8. **Commit format is exact:**

   ```bash
   git -c gpg.format=openpgp -c commit.gpgsign=false commit -m "..."
   ```

   The `-c` flags bypass 1Password's broken SSH-signing fill. **NEVER omit them.**

9. **Tooling invocations:**

   ```bash
   ./.venv/Scripts/python.exe -m pytest ...
   ./.venv/Scripts/python.exe -m mypy src/
   ./.venv/Scripts/python.exe -m ruff check src/ tests/
   ./.venv/Scripts/python.exe -m ruff format --check src/ tests/

   cd frontend && npm run typecheck && npm run build && cd ..
   ```

10. **Audit-at-every-step.** After each task: ruff + mypy + pytest clean. After each wave: `bash scripts/smoke-docker.sh` PASS. After Wave 4 polish: `bash scripts/smoke-e2e.sh` PASS.

---

## Reference docs (where to look up what)

| Question | Doc |
|---|---|
| What does the next phase do? | `docs/superpowers/plans/2026-04-27-v0.3.3-vod-bug-sweep.md` |
| What did the last phase ship? | `docs/superpowers/plans/2026-04-27-v0.3.2-vod-parity.md` + `CHANGELOG.md` |
| What does the system *aim* to be? | `docs/superpowers/specs/2026-04-24-concertpvr-design.md` (foundation) |
| What does VOD aim to be? | `docs/superpowers/specs/2026-04-26-vod-downloads-design.md` |
| What manual checks ship a release? | `docs/release-checklist.md` |
| What's the user-facing pitch? | `README.md` |
| Where do operations notes live? | `docs/operations/` |
| Why does the model look the way it does? | Class docstring on `Recording` in `src/concertpvr/models.py` (live + VOD lifecycles documented) |
| What's the audit history? | `docs/superpowers/plans/2026-04-26-v0.3-audit.md` + `2026-04-26-v0.3-audit-execution.md` |

If something disagrees, **the most recent commit wins**. Specs sometimes lag implementation — the v0.3.3 plan calls out one such case (`LiveProgressBar` text, fixed in Task 14).

---

## Working with subagents

The plan is structured so individual tasks can be delegated to subagents. Recommended approach:

- **Implementation tasks (Wave 1-4)**: dispatch a `general-purpose` agent (sonnet for nuanced tasks, haiku for mechanical ones) per task. Hand it the plan section verbatim plus the current HEAD SHA. Tell it to commit at the end and report the SHA.
- **Audit tasks (Wave 5)**: run inline; the smokes can be foreground with generous timeouts.
- **Code review**: after Wave 4, dispatch a comprehensive audit agent with read-only instructions like the v0.3.2 audit (model after the v0.3.2 audit prompt that lives in your conversation history).

Each subagent dispatch should:
1. Quote the BASE_SHA so the agent knows where to start.
2. Provide the exact code/text from the plan when there is one.
3. List the cross-cutting guardrails relevant to the task.
4. Specify the commit message (the plan provides these).
5. Ask for a concrete report back: SHA, deviations, test status.

---

## After v0.3.3

Once `v0.3.3` is tagged, candidates for v0.3.4 / v0.4 (in rough priority order):

- **Cancel for `vod_downloading`** (currently only `vod_queued` is cancellable). Requires terminating a running yt-dlp subprocess cleanly.
- **Slow-refresh resumption.** If the backend restarts mid-`fetch_full_channel_with_views`, the cache stays in `fetching`. Today the next refresh starts over — fine; if users complain, resume from `progress_pct`.
- **Like counts.** Deferred indefinitely in v0.3.3. Revisit if YouTube data improves.
- **Bulk-approve auto-publish-failed rows** (mentioned in VOD spec §"Open questions").
- **Calendar grid for the Schedule page** (mentioned in `docs/superpowers/plans/2026-04-25-phase-3-schedule.md` — currently a list grouped by day).

These are not in any active plan. If the user wants one, they'll ask for a brainstorm + plan, not for the agent to start.

---

## Working style notes

- **Don't add features the user didn't ask for.** A bug fix is a bug fix. The v0.3.2 audit caught an `auto_publish_after_download` flag that ships UI-configurable but inert at runtime — that's a bug, not a feature, and the v0.3.3 plan fixes it as such.
- **Don't write planning/decision documents unless asked.** This file is the exception because the user asked for it. The plan file is the exception because it was explicitly requested. Otherwise: stay in conversation context.
- **Don't add comments that explain WHAT.** Identifiers should be self-documenting. Comments explain WHY (hidden constraints, workarounds, surprising invariants).
- **Tests are not optional.** Test count goes up monotonically across each release. v0.3.2 ended at 286; v0.3.3 should end at ≥ 290.
- **The user pushes. The agent doesn't.** Unless the user explicitly authorizes it for a specific scope. v0.3.2 push was authorized; v0.3.3 push will be a separate ask.
- **Container state is not session state.** If you bring a container up for testing, bring it down or hand it off explicitly — don't leave it running silently.

---

## Quick-reference: common bash chains

```bash
# Full local audit (after a task)
./.venv/Scripts/python.exe -m ruff check src/ tests/ \
  && ./.venv/Scripts/python.exe -m ruff format --check src/ tests/ \
  && ./.venv/Scripts/python.exe -m mypy src/ \
  && ./.venv/Scripts/python.exe -m pytest -q

# Frontend audit
cd frontend && npm run typecheck && npm run build && cd ..

# Docker smoke (3-5 min)
bash scripts/smoke-docker.sh

# E2E smoke (~5-8 min, hits real YouTube; wipes .local-data + .local-publish)
bash scripts/smoke-e2e.sh

# Standard commit
git -c gpg.format=openpgp -c commit.gpgsign=false commit -m "..."

# View commits since last release
git log --oneline v0.3.2..HEAD
```

---

## When in doubt

- **Stop and ask the user.** The user is responsive and prefers a 30-second clarification over an hour of wrong direction.
- **Read the plan twice.** The architectural decisions are in the preamble; tasks assume them.
- **Trust the audit.** v0.3.2's audit was thorough and produced the v0.3.3 plan. Findings classified as "verified compliant" are not bugs to fix.

Good luck.
