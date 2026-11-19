# Safety review #28 (claude/coord-03)

Pass 1 finished 2026-11-19 ~21:45 UTC, written before opening Codex's review.

## Summary

No critical findings. Nothing is harming the machine or data right now, and no secrets are in the public repo. The isolation layers hold: the file guard, save redirect, HTTP/curl block and firewall rules are all present (firewall rules checked live: inbound and outbound block, pinned to `game\2.2091\GeometryDash.exe`). Defender is on with real-time protection now that Bitdefender is gone.

The real risks are operational:
- the M6 memory guard is blind during solver stalls;
- one supervisor kill can hit a reused PID;
- nothing times out if GD freezes;
- logs grow forever.

The solver's full-replay anchoring is the main efficiency problem, and probably the main driver of GD memory growth.

## Findings

| Rank | File:line | Issue | Scenario | Evidence | Proposed fix |
| --- | --- | --- | --- | --- | --- |
| high | tools/m6/solve_pool.py:74-79 | The memory cap is only checked when the solver logs a progress line (`"  x="`, printed every +300 x). A stalled search never logs one, so GD's memory is never checked while it's stuck. | A level stalls at one point for thousands of evaluations (all practice resets). GD grows past the cap and system RAM runs out, so the user's apps page or fail. On 2026-11-19 only about 1.4-2 GB was free. | Dark Paradise and Stageix spent their 6,000 evaluations at one point (`bad` empty, x stuck). Dark Paradise was at 2,001 MB private at its first check against a 1,200 MB cap. | Check `mem_mb()` every N evaluations (e.g. 50) or every 30 s from `Solver.evaluate`/`run`, and save at the next consistent point. |
| medium | tools/m6/supervise.py:113-116 (also tools/m1/instances_test.py:108) | The end-of-run `kill(discovery(slot)["pid"])` runs without the `alive()` check. `taskkill /F` then hits whatever process now has that PID. `alive()` only matches the image name `GeometryDash`, so it would also match the user's own Steam GD. | The slot's GD already exited and Windows reused the PID for a user app (or the user's real GD), which gets force-killed. | Code path; PID reuse on Windows is routine. (Steam was closed by mistake on 2026-11-19; not caused here, but the same class of risk.) | Before killing, check that the process's ExecutablePath is the repo's `game\2.2091\GeometryDash.exe` and its creation time is after the discovery file's mtime. Apply the same check in `fresh_slot`. |
| medium | gdbot/protocol.py:121; tools/m6/supervise.py:99 | Pipe reads block with no timeout, and the supervisor's `subprocess.run` has no timeout. | GD freezes but doesn't crash (GL stall, modal dialog, deadlock). The worker waits forever and the slot sits idle overnight with no log line. | Code path. The bridge's own pipe thread also waits forever for the reply (control.cpp:1000). | Add a heartbeat watchdog in the supervisor: no new log bytes for about 10 min, plus GD CPU near 0, means kill that slot (with the verified PID) and resume. |
| medium | tools/m5c/solver.py:62, 296-299, 200-231 | Re-anchoring replays the whole committed prefix from 0% every 16 commits, so cost grows with the square of the level length. Long practice replays are also what grows GD's memory. | Long online levels burn most ticks on replays. | Skill Gotten Gains: 35.0M ticks. BNUN: 9.2M ticks for 84 segments. Reflected: 8.5M for 96. | Anchor from the newest verified checkpoint, with a full replay only on a drift or every few hundred commits. Measure ticks/segment before and after. |
| low-medium | mod/src/log.hpp:19; tools/m6/supervise.py:80 | `bridge.log` opens in append mode and is never rotated. Supervisor logs grow forever too. | Weeks of M6 runs: hundreds of MB of logs in `game/2.2091/gdbot`. | bridge.log 9.0 MB (slot 0), 3.4 MB (inst2), 1.7 MB (inst1). | At init, rename to `bridge.prev.log` when it's over 5 MB, keeping one previous file. |
| low (anomaly) | build/m6-scale/solutions/online_148701354.progress.json | Skill Gotten Gains committed 5,234 segments while x only went from about 17,300 to 24,819 (about 1.4 units per segment, against about 33 normally). | The budget is spent committing segments that barely move, possibly a slow-speed or vertical section, or a loop. Guess. | Progress file plus supervise-slot2.log. | Check x per segment around the stall. If it's a stuck loop, have the solver detect "no x progress over N commits". |
| low | mod/src/isolation.cpp:25-35 | The real-save path check fails open: paths over 4*MAX_PATH, `\\?\` prefixes, 8.3 short names and junctions don't match. RemoveDirectoryW, SetFileAttributesW and NtCreateFile aren't hooked. | Only matters if GD (or a mod) built such a path. GD uses getWritablePath, which is redirected. | Code reading. | Normalise with GetLongPathNameW and strip `\\?\`; hook RemoveDirectoryW and SetFileAttributesW. Fail closed on overlong paths. |
| low | mod/src/isolation.cpp:145-149 | `curl_multi_perform` passes through and relies on the firewall rule. The rule pins the exe path, so moving the repo silently opens the network again. | Repo moved or renamed: the firewall no longer matches, and curl multi traffic reaches the internet. | Rules checked live today (present, enabled). | Block `curl_multi_perform` too (return CURLM_OK with no transfers), or have `hello` report the firewall state. |
| low | mod/src/control.cpp:987 | The pipe has the default DACL. Any process of the same user can connect and drive GD, including `debug_peek`. | Local malware or a stray script drives the bot. Same-user only (remote clients are rejected). | Code. | Optional: an explicit DACL for the current user SID, and `debug_peek` behind an env flag. |
| low | gdbot/levels/online.py:53, 91 | `resp.read()` and `gzip.decompress` have no size limit. | A malicious or corrupt server response (a decompression bomb) runs Python out of memory. HTTPS to boomlings, so unlikely. | Code. | Cap the read at 32 MB and decompress in chunks up to 64 MB. |
| low | tools/gd_save.py:28-30 | Saves are written in place: not atomic, no backup, no check that GD is closed in that slot. | A crash mid-write, or GD running, corrupts the bot's save (never the real one). | Code. | Write `.tmp` then replace, keep `.bak`, refuse while the slot's discovery PID is alive. |
| low (guess) | tools/m5c/solver.py:226 | `rebuild` recurses on every drift. | Many drifts on a long level could hit the recursion limit. | None observed. | Turn it into a loop. |
| info | public repo | The repo is PUBLIC (the site reads `main`). It contains 12 third-party online level files (`levels/online/`), and the path `C:\Users\user` in two tooling files. | Nothing sensitive found: no tokens or keys, and the user's email isn't in tracked files. | `git grep` for tokens, keys and the email. | Decide whether `levels/online/` should stay public. |

## Reviewed

- **Bridge:** mod/src/isolation.cpp, main.cpp, control.cpp (step, step_seq, debug_peek, load_level, pipe thread, window procedure), hooks.cpp (PlayLayer lifetime, draw-skip), log.hpp. Also mod/CMakeLists.txt (/MD CRT, shared heap) and injector/main.cpp.
- **Python:** gdbot/instances.py, runmode.py, protocol.py, levels/online.py; tools/m5c/solver.py, m6/solve_pool.py, m6/supervise.py, gd_save.py, m1/instances_test.py.
- **Automation:** dashboard/nightly_refresh.ps1 (private index, no force push), dashboard/power_sampler.ps1.
- **Live checks:** firewall rules, Defender status, log, build and .git sizes (.git 9.3 MB, build/m6-scale 37 MB, venv 771 MB), repo visibility, secret scan.

Not reviewed in depth: site/app.js rendering (no innerHTML/eval found), tools/m2-m5 one-off studies, mock_bridge.

## Cross-check (written 2026-11-19 after reading codex/safety-01's review)

**Agree (both reviews found it):**
- **Memory guard blind during stalls** (Codex 3 / mine high). Both rank it high.
- **Unverified PID kill** (Codex 1 high / mine medium). I raise mine to **high**: Codex also points out that the failed kill is ignored and the slot is still reported closed.
- **Pipe deadlines and DACL** (Codex 4 / mine medium + low).
- **Unbounded downloads and decompression** (Codex 6 medium / mine low). I'd keep it low-medium: it's HTTPS to one server, but the cache is also untrusted input to the native loader, which is a fair point.
- **gd_save in-place writes** (Codex 7 / mine low).
- **Log and telemetry growth** (Codex 10 / mine low-medium). Measurements match: slot 0 at 8.6 vs 9.0 MB.

**Partly dispute: firewall (Codex 2, high).** Codex didn't verify the host. I checked live: both GDBot rules (inbound and outbound block) are present, enabled, and pinned to `C:\Users\user\Documents\babyzoink\game\2.2091\GeometryDash.exe`. So nothing is exposed today, and I'd rank it **medium**. I agree with the fix: the launcher should verify the rule (or block curl_multi in-process) and fail closed. The real trigger is moving the repo.

**I missed these and agree with them:**
- 5: request-id error path can throw outside the handler. Inspection only on Codex's side; plausible.
- 8: sections.py parallel writers erase each other's boundaries. This matters now that two slots run at once.
- 9: resume rebuilds candidate iterators and repeats rejected work. It interacts with #31.
- 11: nightly plumbing commands unchecked; shared index path.
- 12: mute_gd.ps1 also mutes the user's own Steam GD.
- 13: unpinned native dependency hashes; checkpoint provenance.

**Codex didn't list these:**
- O(n²) full-replay anchoring (tools/m5c/solver.py:62, 296-299). Skill Gotten Gains spent 35M ticks.
- The Skill Gotten Gains anomaly: 5,234 segments for about 7,500 x.
- `rebuild` recursion.
- `levels/online/` third-party files in the public repo.

**Result:** the agreed fixes are queued as `open` rows #33-#44 in STATUS.md. Bridge rows (`mod/`) still go through Claude for review per the protocol.
