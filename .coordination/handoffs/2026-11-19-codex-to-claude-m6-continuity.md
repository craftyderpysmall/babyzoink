# Handoff: M6 continuity if Codex becomes unavailable

From: codex/m6-resume-01
To: claude
Created: 2026-11-19
Status: info (standby for takeover)
Related task: tasks/M6-scale.md, queue #19

## Latest confirmed state

Steam is signed in again. GD slot 2 is handling the even-index M6 online pilot. At restart, Skill Gotten Gains (online:148701354) resumed from segment 304 at x=16,393, and the new solver rebuilt an older eligible checkpoint instead of falling back to 0%. Six drills have verified clears. Stageix and Moving Obstacles reached 6,000 evaluations and have no clean clear. The next scaling comparison needs ten verified online training clears.

## Find live state

- build/m6-scale/online-run-state.json records the current worker's game PID, slot, budget, log and exit code. Confirm the PID in slot 2's discovery file and the actual process. A stale running state can survive an interrupted shell.
- build/m6-scale/online-shard0-older-anchor.log names the active level and shows solver progress. In build/m6-scale/solutions/, each *.progress.json contains the latest durable prefix, and the corresponding result JSON says whether a clean run verified a clear.
- .coordination/tasks/M6-scale.md holds the running experiment notes. Check the existing runtime claim before taking over. Keep Steam open while either game slot is needed.

## Resume after the current process exits

Use the existing project venv and launch the claimed slot only through gdbot-launch.exe. The worker command below skips verified levels and levels that already reached this budget. Recalculate --limit if you need the same ten-level batch boundary.

    .\build\gdbot-venv\Scripts\python.exe -B -u tools/m6/solve_pool.py --slot 2 --split online --shards 2 --shard 0 --budget 6000 --look 40 --present-every-ms 1000

Check available RAM before opening another slot. The long online run previously reached about 2.4 GiB working set. Keep the frozen evaluation levels out of training. The dashboard uses the ledger and curve reports described in the task record.

07:09 UTC: Skill Gotten Gains reached depth 319; restore validation has since rejected several older checkpoints and the search is re-anchoring. Treat the older-anchor speedup as provisional. Slot 2 is still active, with no new verified online clear.

07:11 UTC: The running revision tested older checkpoints down to depth 1 after the failure at depth 319. The next worker launch will skip the rest of the older fallbacks after the first one fails and retry from 0%. A focused test passed. The current worker is still running its imported revision and has already worked through the old anchors.

User paused Codex. Slot 2 stopped. Latest saved checkpoint: Skill Gotten Gains, segment 320, x=17317, 1013 evaluations. Wait for the user before resuming this run.
