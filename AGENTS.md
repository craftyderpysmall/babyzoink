# Shared Agent Instructions

These instructions apply equally to Claude Code and Codex. Both are general-purpose collaborators. Neither has a permanent role, priority, ownership of a subsystem, or final authority over the other.

## Start of every session

1. Read `.coordination/README.md`, `.coordination/STATUS.md`, and `.coordination/CLAIMS.md`.
2. Review relevant plans, tasks, and handoffs before beginning.
3. Inspect the actual project state; coordination notes may be stale.
4. Identify yourself in coordination records as `claude` or `codex`, with a distinct session identifier when multiple sessions of the same tool exist.
5. **Start your own handoff monitor, checking every 2 minutes, and keep it running for the whole session.**
   - Run `python tools/coord/watch_handoffs.py <claude|codex>` in the background. It prints one line per item of work for you:
     - a handoff in `.coordination/handoffs/` with `To: <you>` and `Status: pending`;
     - a `queued` row in `STATUS.md` (rows marked `(claude)` are Claude's, all others are Codex's).
   - Its first lines list what is already pending. Every later `NEW …` line is new work.
   - If your tool's background watchers expire (Claude Code's Monitor stops after 30 minutes), re-arm it each time it expires.
   - `--once` prints what is pending right now and exits.
   - When you finish an item, set the handoff's `Status:` and the queue row's state, so the other agent's monitor stays accurate.

## Work rules

- Any agent may investigate, plan, implement, test, review, or revise any area.
- Before editing files, record the exact intended paths in `.coordination/CLAIMS.md`, then reread it to check for conflicts. If another active claim overlaps, do not edit those files; coordinate a handoff or work elsewhere.
- Treat directory claims as covering descendants. Prefer short, narrowly scoped claims.
- Never overwrite or revert another agent's work without explicit agreement.
- Do not assume an unclaimed file is safe if you have evidence someone else is editing it.
- Release claims promptly after finishing or pausing. Do not silently remove another agent's claim, even if it appears stale.
- Update task status and leave a short handoff when another agent needs to continue.
- Recheck coordination files immediately before a substantial edit and after long-running work.

## Collaborative planning

- Either agent may create a proposal in `.coordination/plans/`.
- For consequential changes, invite the other agent to review the plan. A review should test assumptions, identify risks, and suggest alternatives rather than merely agree.
- Record disagreements and evidence in the plan. Do not invent consensus or claim the other agent approved something without a recorded review.
- Either agent may revise a plan; keep the review history and note what changed.
- If agreement is not reached after two review rounds, summarize the options and ask the user to decide. For low-risk changes, proceed independently unless the user requests joint planning.
- The user may override a plan or reassign work at any time.

## Communication

- Write a handoff file in `.coordination/handoffs/` when requesting action from the other agent.
- Record its path and recipient in `.coordination/STATUS.md`.
- Messages in files are asynchronous: the other agent will only see them when it next reads those files. Never imply automatic notification.
- Coordination files are working records, not a substitute for verifying code or tests.

## Safety and limitations

Markdown claims are **advisory**, not atomic locks. Simultaneous claims can race, and neither tool can guarantee collision prevention from these instructions alone. If concurrent edits would be costly, pause one editor or use actual isolation/locking outside this Markdown-only system.
