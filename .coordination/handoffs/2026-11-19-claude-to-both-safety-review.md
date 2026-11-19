# Handoff: two independent reviews for leaks and unsafe code (user request)

To: codex (queue #27) and claude (queue #28)
From: claude/perf-01
Created: 2026-11-19
Status: completed

The user asked for two independent reviewers ("2 sets of eyes") to review the whole codebase thoroughly for memory and storage leaks and for anything that looks unsafe or dangerous.

## Rules
1. **Independent first pass.** Write your own findings to `.coordination/reviews/2026-11-19-safety-review-<codex|claude>.md` before you open the other reviewer's file. Note in your file when you finished pass 1.
2. **Cross-check second.** Once both files exist, read the other review and add a "Cross-check" section to your own: agree, dispute with evidence, or add what you missed. Don't edit the other agent's file.
3. **Review only.** Don't fix anything during the review. List each fix as a proposed queue row (file, change, risk); Claude turns agreed fixes into queue rows. The exception is something actively harming the user's machine or data right now: stop it, record what you did, and tell the user.
4. Rank each finding (critical / high / medium / low). Give the file:line, a concrete failure scenario, and the evidence: a measurement, a repro, or a code path. Mark guesses as guesses.
5. The game runtime isn't needed. If you want to measure something live, claim a free slot and check available RAM first; the reference numbers are in docs/PROTOCOL.md.

## Scope (minimum; go wider if you find more)
- **Memory in GD:** the bridge (`mod/src/*.cpp`): hooks, per-episode containers (`g_cps`, object cache, traces), JSON buffers, threads and handles. GD-side growth from practice resets and toggles is already measured (docs/PROTOCOL.md, "Memory growth during long searches"); look for what the bridge could do about it.
- **Memory in Python:** long-running loops in `tools/m5c/solver.py`, `tools/m6/*.py`, trainers (`gdbot/`), `tools/site/*`: unbounded lists, caches, histories, reply objects kept forever.
- **Storage:** files that grow without limit or rotation (`game/2.2091/gdbot/bridge.log` is 8.7 MB and never rotated; `build/` is 1.2 GB), checkpoints, models, logs, downloads (`build/m6-scale/online`), the nightly dashboard commits growing the git history, temp files.
- **Unsafe or dangerous:**
  - Native code: SEH and `safe_copy`, hard-coded offsets and RVAs, calls into GD from the wrong thread, pointer lifetimes (`g_layer`, `g_skip_scene`, checkpoint pointers), MinHook install and uninstall, input blocking.
  - Isolation: could anything touch the user's real GD save (`%LOCALAPPDATA%\GeometryDash`) or the network? Check `isolation.cpp`, the save redirection and HTTP blocking, and `tools/gd_save.py` paths.
  - Process control: `Stop-Process`/kill calls, launcher behaviour, priority and affinity changes, anything that could close the user's apps. Steam closed by mistake on 2026-11-19 took both GD slots down.
  - Shell and network: subprocess with shell strings, downloads (`gdbot/levels/online.py`), untrusted level data parsed in Python or by GD, zip/gzip/base64 decoders (sizes, bombs).
  - Git and automation: the nightly Windows task that commits and pushes to `main`, the cloud routine, any credentials or tokens in the repo or logs, files outside the repo being written.
  - Anything that disables or weakens system security (for example Defender changes).

## Output
Each review file: summary, findings table (rank, file:line, issue, scenario, evidence, proposed fix), list of what you reviewed, and the cross-check section. Set your queue row to `done` when the cross-check is written.
