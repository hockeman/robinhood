# Persistence & serialization protocol (canonical, replaces every earlier convention)

**Canonical branch: `claude/trading-state`.** This is the one and only
place run state lives. `main`, `claude/journal`, and every
`claude/clever-thompson-*` / other per-session throwaway branch are
retired as persistence targets — they still exist (nothing was deleted)
but a session must never read them for current state and must never treat
a push to one of them as a successful save.

Why: this repository's GitHub default branch is stuck on the original
bootstrap commit and a Claude Code on the web session always checks out
whatever branch the harness assigns it or the repo's default branch — never
a fixed branch this document could rely on. So every session must
*explicitly* fetch and switch to `claude/trading-state` itself, every time,
regardless of what branch it woke up on. See `RECONCILIATION.md` for the
full incident history this replaces.

## Startup (every run, before initializing or interpreting any state)

1. `git fetch origin claude/trading-state`
2. If the fetch fails because the branch does not exist yet: this is the
   very first run after reconciliation, or something deleted it — stop,
   do not fabricate a branch from whatever the session cold-started on,
   and report the exact error. (Normally this branch exists; a real
   maintenance/setup run is what creates it.)
3. `git checkout -B claude/trading-state origin/claude/trading-state` (or
   equivalent) — this is the *only* source of truth for `state.json`,
   `notification_state.json`, `trades.jsonl`, `journal/`, and the
   `reporting/` templates. Do not read any of these from the branch the
   session happened to start on, from `main`, or from `claude/journal`.
4. Proceed with Step 0 orientation (STOP check, config, time) using the
   files as read from `origin/claude/trading-state`.

## Save (every run that changes state, at the end of the run)

1. Commit `state.json` / `notification_state.json` / `trades.jsonl` /
   the new `journal/YYYY-MM-DD-HHMM.md` on top of the exact commit fetched
   in step 1 above (i.e. `HEAD` must still be `origin/claude/trading-state`
   as of the start of this run — do not rebase onto something else first).
2. `git push origin HEAD:claude/trading-state` — a **plain, non-force
   push**.
3. **If the push is rejected as non-fast-forward:** this is the atomic
   claim mechanism (see below) telling you another run's save landed on
   `claude/trading-state` after your fetch in step 1. Do not force-push.
   Do not fall back to any other branch and call it done. Instead:
   `git fetch origin claude/trading-state`, re-apply your changes on top
   of the new tip (merge or replay — re-derive the journal entry / state
   diff against the new base rather than blindly overwriting it, per the
   standing instructions' "do not blindly merge conflicting JSON" rule),
   and push again. Retry at most once more automatically; if it fails a
   second time, stop, take no trading action this run, and report the
   exact git/GitHub error (branch name, both SHAs, the actual rejection
   message) rather than silently choosing a different branch.
4. **If the push fails for any other reason** (auth, permissions, network):
   report the exact error. Do not bypass it by pushing elsewhere, and do
   not claim the run's state was saved.
5. A run is not "done" until this push has succeeded and you have (this
   run) observed the new tip SHA — either from the push command's own
   output or a follow-up `git ls-remote origin claude/trading-state`. Do
   not claim persistence from a local commit alone.

## Serialization / the "shared lock"

There is no separate lock file, and a lock file would not work anyway — a
fresh clone each session means a local lock is never seen by the next
session (this is explicitly why the standing instructions call out that a
local file in a fresh clone is not a shared lock).

Instead, the **plain `git push` to `claude/trading-state` in Save step 2
above is itself the atomic, shared claim.** GitHub only accepts that push
if the pusher's local `claude/trading-state` tip (from the fetch in
Startup step 1) is still the branch's actual current tip — exactly a
compare-and-swap on the branch ref. Two sessions that both fetch, both do
work, and both try to push cannot both succeed: the second one's push is
rejected, which is the reliable "another run got there first" signal Step
0's serialization requirement asks for. This works across fresh clones,
unlike a lock file, because the compare-and-swap happens on GitHub's
server, not in either session's local filesystem.

**If reliable serialization cannot be established** — e.g. the push is
rejected repeatedly, or `claude/trading-state` cannot be fetched/pushed at
all due to a permissions error — the run must not authorize any new
trading activity (no new entries; a genuinely missing protective order may
still be added, since leaving a position unprotected is worse than the
serialization risk, but nothing else). Report the precise error.

## What this deliberately does not do

- It does not require a new bot/token/external lock service.
- It does not require the GitHub default-branch setting to be correct
  (though fixing that — see `RECONCILIATION.md` — removes the need for
  every session to explicitly re-checkout `claude/trading-state`, since a
  correct default branch would make that the natural starting point).
- It does not create a new "authoritative state branch" per session. Every
  session pushes to the *same* `claude/trading-state` branch, never a new
  one.
