# Claude–Codex Coordination

This folder is a shared, human-readable collaboration protocol. It contains no executable coordinator, background listener, automatic notifications, or enforceable file locks.

## Files

- `STATUS.md` — active work, pending reviews, and handoff inbox.
- `CLAIMS.md` — temporary, cooperative edit claims.
- `plans/PLAN_TEMPLATE.md` — shared proposals, critique, and decisions.
- `tasks/TASK_TEMPLATE.md` — task ownership and completion notes.
- `handoffs/HANDOFF_TEMPLATE.md` — asynchronous agent-to-agent requests.

## Routine

1. Read `STATUS.md` and `CLAIMS.md` at the beginning of each session and before editing.
2. For nontrivial work, create a task from the template; for significant design work, create a plan.
3. Claim only the paths you are about to edit. Recheck for overlapping claims.
4. If another agent is needed, write a handoff and add it to the STATUS inbox. Ask the user to direct the other agent to read it, or wait until it next checks.
5. When finished, update the task, release claims, and record outcomes.

## Joint planning loop

1. Proposer writes a plan with questions and a proposed approach.
2. Reviewer adds a distinct review section, objections, alternatives, and evidence.
3. Proposer responds point by point and revises the proposal.
4. Reviewer confirms agreement or states remaining disagreement.
5. If unresolved after two rounds, present options to the user; do not fabricate agreement.

Either agent can propose or review. No permanent leader exists. Plans may be reopened when evidence changes.

## Claim rules

Claims are path-based. A claim for `src/` overlaps every path below `src/`. Claims should list individual files where practical. If two agents might write the same path, one must wait or explicitly transfer the claim. When a claim seems abandoned, ask the user before clearing it. This is a social protocol only; simultaneous read/write races remain possible.

## Suggested prompts

**To start joint planning:** “Read AGENTS.md. Create a proposal for [goal] in .coordination/plans/, and request a critical review from the other agent. Don't claim agreement before that review happens.”

**To review:** “Read AGENTS.md and the pending plan in .coordination/STATUS.md. Critique it independently, record your review, and propose improvements. Don't implement yet.”

**To execute:** “Read AGENTS.md and the approved plan. Claim only the files you need, check for overlap, implement your portion, release claims, and leave a handoff.”
