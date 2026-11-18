# Plan: Geometry Dash learning bot ("babyzoink")

Status: agreed (claude/plan-01 + codex/gd-review-02, 2026-11-18)
Proposed by: claude/plan-01
Updated: 2026-11-18 (agreed after review round 2)
Related task: none yet (tasks get created per milestone once the plan is agreed)

## Goal and success criteria

Build an ML agent that plays Geometry Dash, learns general gameplay gimmicks rather than memorizing one level, and keeps improving so harder levels take fewer attempts, the way a human player does.

Success criteria:
- Compared with earlier training generations, **attempts-to-first-completion on held-out levels** goes down and **zero-shot % progress** goes up.
- A level only counts as "beaten" on a full run from 0%.

- **M1:** tick-stamped hold/release and full reset work in an isolated local profile. Online submission and account writes are blocked *before* any automated completion happens.
- **M2:** replaying a tape gives identical per-tick traces: position, velocity, mode, button/queue state, trigger/activation events, and the terminal event and tick. "Identical" must hold across normal, dedicated, and background stepping; visible and minimized windows; same-process resets; and fresh launches. The harness reports the first divergent tick. Throughput is measured end to end, not assumed.
- **M3:** a small CPU baseline is compared on authored drills and on shifted/recombined *unseen* variants.
- **Main metric** (with a frozen protocol: held-out level revisions, seeds, the initial model, and the adaptation budget per comparison):
  - First-run progress.
  - Capped full-run solve rate.
  - Attempts to first clear, with failures counted at the cap.
  - Practice cost in resets, simulated steps, and wall time.
  - The learner is reset to its generation checkpoint before adapting to each held-out level. A separate validation pool is used for development decisions.
- **Unit tests:** observation encoding, curriculum sampling, the IPC protocol (using a mock bridge), and the replay-trace diff tool.

## Context and constraints

The repo is empty apart from the Claude/Codex coordination scaffolding. The goal is an ML agent that plays Geometry Dash, learns general gameplay gimmicks rather than memorizing one level, and keeps improving so harder levels take fewer attempts, the way a human gets better.

User decisions so far:
- **Game interface:** a custom injected DLL mod, not Geode, because the user finds Geode's version compatibility unreliable. Geode v6 alpha now supports 2.209x (see facts below); the user's decision stands, but they have been told.
- **Observation:** game state read from memory. No pixel model.
- **Compute:** CPU only for now; a cloud GPU is possible later.
- **Success metric:** a curriculum plus few-shot test. Attempts-to-beat on held-out levels should drop as training progresses.
- **Levels:** official levels for the ladder; custom online levels, chosen by gimmick, for the held-out test.
- **Speedups:** practice-mode checkpoints, and the user asked about adding start positions too. Answer below: yes, use both.
- **Run modes:** two, switchable. Dedicated (full speed) and Background (throttled while the user uses the PC).
- **Version:** the user has GD **2.2091** (confirmed from the build ID and the exe). Stay on top of update information.
- **Who builds it:** mostly the agents. The user tests in-game and gives direction.

### Current facts (re-verified 2026-11-18; re-verify at every milestone start)
- **Installed build: 2.2091.**
  - Steam buildid 26002420 (2026-10-17), PE timestamp `0x6AD2D987`.
  - SHA256 `4EEE06D5C2E2213B4BA2B1F6233DD426BBDD0E9B29D7C375E499516B6F8F69D5`.
  - Path: `C:\Program Files (x86)\Steam\steamapps\common\Geometry Dash`.
  - Steam `AutoUpdateBehavior` is 0 (always update), so the frozen copy is required.
  - Codex independently matched the build ID and hash.
- 2.209 shipped on 2026-10-15 with the native Start Position Switcher and death tracking. The 2.2091 hotfix shipped on Windows around 2026-10-17/18.
  - 2.2091 and 2.209 share a displayed version string, so builds are identified by the exe hash only.
- **Correction:** an earlier revision said no `bindings/2.2091` exists. That was wrong.
  - `geode-sdk/bindings` has a separate `bindings/2.2091/GeometryDash.bro` (about 1.4 MB, actively committed as of 2026-11-18).
  - It gives Windows RVAs that differ from 2.209's. Example: `GJBaseGameLayer::handleButton` is win `0x33c5b0` in 2.2091 vs `0x339ac0` in 2.209.
  - Issue #1360 was about porting from 2.209, and it was closed. Claude verified this directly.
- Geode v6.0.0-alpha.1 (2026-11-01) and alpha.2 (2026-11-15) are prereleases supporting 2.209x. v5.11.x does not.
- **Prior art:** gdsolver (github.com/gdsolver/gdsolver) is a 2.2091 Windows automation tool.
  - Its docs cover replay determinism, checkpoint restoration gaps, rotated gameplay, and exe/DLL build checks.
  - Use it as reference evidence. Check its license before reusing any code.
- Sources: [SteamDB 26002420](https://steamdb.info/patchnotes/26002420/), [bindings 2.2091](https://raw.githubusercontent.com/geode-sdk/bindings/main/bindings/2.2091/GeometryDash.bro), [Geode releases](https://github.com/geode-sdk/geode/releases), [gdsolver](https://github.com/gdsolver/gdsolver), [RobTop on X](https://x.com/RobTopGames/status/2110855582223569400)

## Proposed approach

**1. State, not pixels.** The bot reads the real hitboxes. Visual gimmicks are therefore irrelevant: fake spikes, invisible blocks, alpha/colour tricks, camera moves, and decorations that look like hazards. It sees what the game actually collides with. A pixel model would add CPU cost and make those tricks a weakness. We drop it. Pixel input could only come back as a far-future "human-fair" stretch goal.

**2. The observation is built to generalize, and it is treated as partial.** Each object is encoded by *what it is*, in gameplay coordinates, not by where it sits in a particular level. Level IDs and absolute progress are never policy inputs. This is a privileged-state benchmark (hidden hazards are visible to the policy), and we label it that way.
- **Player features, one set per body; dual mode gets two:**
  - y, actual velocity, gameplay orientation/rotation, and game mode (cube/ship/ball/UFO/wave/robot/spider/swing).
  - Speed tier, gravity, mini, on-ground/contact flags.
  - Held/buffered input state, and dash/orb-activation flags.
- **Objects:**
  - Collision-relevant geometry queried *from the game's collision data*, not sprite bounds.
  - Current solidity/activation state.
  - Actionable orb, pad, and portal parameters.
  - A stable object ID for motion across samples.
- **Lookahead window:** sized in *time-to-contact*, capped spatially. Truncation and unsupported mechanics are reported explicitly.
- **Hidden state:** short history, selected trigger state, or recurrence is added only when paired states with the same observation are shown to lead to different transitions.
- **Encoder:** compare a sorted top-K feature vector against a masked pooled set encoder on the same drills and the same CPU budget. Keep whichever wins.
- **Scope:** start with a measured supported slice: static cube terrain, hazards, and a few labeled interactions. Add modes one at a time, each against small authored diagnostic levels.
  - Independent two-player controls are out of scope; one shared button bit can't express them.

**3. Action and timing.**
- The action is binary hold/release, with input edges applied at a defined phase of the tick.
- The bridge advances exactly k completed physics ticks, or stops at the first terminal tick, and returns a post-step observation stamped with episode ID and tick.
- Game state is touched only on the game thread; the transport waits separately.
- The tick boundary (command processing vs scheduler vs render) is verified in 2.2091 before a hook is chosen.
- k=1 is supported from day one. For k=4 (60 Hz decisions), all four decision phases are tested on a timing fixture with known-good inputs. Sections unreachable at k=4 get a finer cadence or are excluded from that evaluation tier.
- Classic mode only.

**4. Learning algorithm.**
- **Baseline:** SB3 PPO on CPU with a small feed-forward policy. It is compared against a simple timing heuristic, and against behavior cloning from verified *auto-generated* tapes if exploration is slow.
  - The user did not opt into imitating their own replays, so their replays are not used unless they ask.
  - A custom PPO is built only when a measured limitation requires it.
- **Reward:** verified level progress, not raw world Δx, because rotated or teleported sections break that link. Early drills are explicitly forward-only, so Δx is acceptable there. Plus a death penalty and a completion bonus.
- "Fewer attempts over time" comes from two things:
  - (a) Generalization from the shared object encoding plus a broad curriculum.
  - (b) A few-shot adaptation phase on each new level: short fine-tuning with practice sampling. Its cost is the attempts-to-beat metric.

**5. Practice: start positions AND checkpoints, each with its own evidence requirement.**
- **Start positions:** a synthetic drill distribution spread across the level (drill hotspots, reverse curriculum). Allowed only where the preceding trigger state is irrelevant.
- **Checkpoints:** each checkpoint suffix is validated against a continuous replay of the same input tape, covering held input, dual state, moving objects, and pending triggers.
  - If restore parity fails, fall back to replaying the recorded prefix.
  - Reset cost is measured.
- **Training loop modeled on how players learn:** drill hotspots, then do full-run attempts. A completion counts only after a clean normal start from 0%.

**6. Two run modes, switchable while training runs** (CLI `gdbot mode dedicated|background`, or a hotkey caught by the mod):
- **Dedicated:** uncapped time scale, rendering skipped or decimated, all CPU threads, and later optionally several GD instances.
- **Background:**
  - GD windowed/minimized at low render rate with BELOW_NORMAL process priority.
  - Torch limited to about 2 threads and the simulation speed capped.
  - Inputs go into the game internally, not as OS keypresses. GD never needs focus and never types into your other windows.
  - You can game at the same time, though heavy games will compete for CPU. You can't play *GD itself* in the same instance; pause the bot for that.

**7. Version handling (user priority: stay current).**
- **Build identity:** the installed exe is identified by SHA-256, with the Steam build ID recorded. Any companion DLL whose entry points we use gets fingerprinted too.
- **Frozen folder:** the frozen copy is verified to actually launch the pinned exe, with a separate save context.
- **Address map:** the public `bindings/2.2091` file is the research reference, pinned to a specific bindings commit. The runtime is our own.
  - The primary mapping is **verified RVAs keyed by exe hash** in `mod/offsets/<sha256-prefix>.json`. Byte signatures are a *porting aid* for future patches, not the source of truth.
- **Functions and memory layouts** are separate compatibility work. A located function can still have changed semantics or member offsets. Only the minimal field surface is mapped and verified, milestone by milestone:
  - M1 surface: gameplay update boundary, jump press/release, full reset, live player pose/velocity.
- **Unknown builds** and ambiguous or missing entries leave the bridge *inactive*.
  - If an essential entry is missing, manual mapping is time-boxed on the exact exe, then the blocked capability is reported.
  - A Geode reference probe is a fallback only if the user decides on it.
- An `UPDATING.md` runbook covers new patches: check the news and the bindings repo, re-hash, re-map, re-verify.

**8. Safety and fair play.** The bot must never pollute the real leaderboards.
- The mod blocks online submission of completions, stats, and leaderboard data, plus 2.209's death/play telemetry. It runs in a separate save profile with no account writes.
- This must be in place *before* the first automated completion (M1 gate).
- Online levels are cached once, then played offline. Isolation is verified.

### Architecture / repo layout

```
mod/                C++ x64 DLL (CMake, MSVC) + MinHook
  src/hooks.cpp       GJBaseGameLayer/PlayLayer update, resetLevel, destroyPlayer, handleButton, CCScheduler (timescale), draw skip, online-submit block
  src/state.cpp       player + object extraction (hitbox, category)
  src/ipc.cpp         named-pipe or localhost TCP, lockstep protocol (msgpack)
  src/practice.cpp    spawn-at-x start pos, checkpoint create/load
  offsets/<sha256>.json verified RVAs + field offsets per exe hash; signatures as porting aid
injector/           tiny exe: find GD process, LoadLibrary via CreateRemoteThread
gdbot/              Python package
  env.py              Gymnasium env over IPC (reset(level, start_x | checkpoint), step(action))
  obs.py              observation encoding/padding
  model.py            set-encoder features extractor
  train.py            PPO training loop, mode switch
  curriculum.py       level ladder, death-hotspot sampling, promotion rules
  replay.py           tape record/replay + per-tick trace diff (first divergent tick)
  bench.py            staged throughput benchmarks
  levelgen.py         (deferred) seeded parameterized drills, solvability-checked
  eval.py             held-out few-shot eval, attempts-to-beat
levels/             drills/ (original hand-authored editor drills + known-good tapes), curriculum.yaml, validation.yaml, heldout.yaml (frozen revisions + gimmick tags)
docs/               UPDATING.md, OFFSETS.md (how addresses were found)
```

### Milestones

- **M0: identify and map.**
  - Hash the exe and companion DLLs, make the frozen copy, and confirm it launches the pinned exe with a separate save.
  - Pin a bindings commit.
  - Map and verify (with x64dbg breakpoints and live semantics) only the M1 surface.
- **M1: isolated bridge.**
  - Inject the DLL. Get tick-stamped hold/release and full reset working.
  - Block online submission, account writes, and telemetry *before* any automated completion.
  - The user verifies in-game.
- **M2: parity and throughput.** M2 is a gate: nothing else depends on numbers it hasn't measured.
  - **Parity:** the replay-trace parity suite runs across modes, window states, resets, and fresh launches, on a basic, a timing-sensitive, and a trigger-heavy fixture. It checks that physics stays frozen while waiting on a command. It also checks mode-switch parity and the k=1 and k=4 phase tests.
  - **Staged throughput:** native replay with and without render suppression → IPC round trip → observation extraction → full PPO collection plus updates.
  - **Measured:** sustained ticks/s, transitions/s, p50/p95 step latency, reset cost, and CPU use.
  - **Background mode:** foreground frame-time impact is measured with training paused vs active.
  - 10× real time (about 600 transitions/s, about 1.67 ms per transition) is a target to measure, not an assumption. Profile before optimizing (static geometry cache, compact fixed-width payload, draw decimation if full suppression breaks parity) or adding instances.
- **M3: first learning.**
  - Original hand-authored drills: jump timing, an orb, a gravity/speed change, moving geometry. Each has a known-good tape.
  - The CPU baseline (PPO with top-K vs set encoder, plus the heuristic) is evaluated on unseen shifted/recombined variants.
  - Stereo Madness is a smoke test only.
- **M4: practice.** Start positions and checkpoints with parity validation, prefix-replay fallback, hotspot sampling, and the clean-0% gate.
- **M5: curriculum.**
  - Expand drills mode by mode, then the official ladder, then promotion rules.
  - Build a seeded levelgen only if drill coverage limits progress, with solvability checked at the chosen cadence.
- **M6: evaluation and polish.** Frozen-protocol held-out eval, metric dashboard, finalized mode toggle.
- **M7 (stretch):** multiple isolated instances (only after measuring single-instance limits), cloud GPU, platformer mode.

## Alternatives and tradeoffs

- **Geode mod instead of a custom DLL.** Rejected by the user over compatibility concerns. Since then, Geode v6 alpha (a prerelease) added 2.209x support. We still use the public bindings as reference data. A Geode reference probe remains a user-decided fallback.
- **Screen capture / pixel observation.** The user first chose this, then switched to a mod. Pixels-only would run at real time with no speedup, would be heavy on CPU, and could be fooled by visual tricks. Dropped. It could only come back as a far-future "human-fair" stretch goal.
- **Practice checkpoints only.** Rejected: start positions jump straight to any point in a level. Both are kept (see decision 5).
- **Imitation learning from user replays.** Offered but not selected by the user. Can be revisited if PPO turns out to need too many attempts.

## Risks, assumptions, and open questions

- **Address mapping risk is lower than first thought,** since `bindings/2.2091` exists. The remaining risk is verifying semantics and member layouts for our minimal surface.
- **Determinism:** gdsolver reports click-on-steps replays repeat at fixed settings, but collision differs across resolution settings. Pin the settings; M2's per-tick parity suite is the gate.
- **CPU throughput** limits how far training can go. Hard demons with frame-perfect inputs are a long-term goal, not an early target.

Assumptions and open questions for the reviewer:
- The installed build is 2.209 according to the user, but it may actually be 2.2091. M0 confirms this.
- Lockstep determinism, CPU throughput, the encoder choice, and levelgen are no longer open guesses. Each now has a measurement gate (M2/M3/M5).
- Interpretation to confirm with the user: background mode means the user can play *other* games while the bot trains.

## Review round 1 — codex/gd-review-01, 2026-11-18T05:40Z

**Disposition.** Revise M0–M3 before implementation. The custom DLL, state-only policy, and CPU-only setup are viable directions. Exact-build coverage, replay fidelity, and end-to-end throughput each need their own acceptance test. This review used the public sources below. The checkout contains coordination files only. I independently matched the Steam manifest build ID (26002420) and executable SHA-256 recorded above for the installed 2.2091 build. Runtime parity and throughput remain unmeasured.

### Build identity and offsets

- **Correct the version premise.** RobTop's October 15 Steam announcement confirms 2.209 and the Start Position Switcher. The developer's App Store history lists the 2.2091 bugfix on October 19 for iOS. The Windows 2.2091 hotfix is independently attested by gdsolver's October 18 release. Geode v6.0.0-alpha.1 announced 2.209x support on November 1, and the bindings repo has separate Windows entries for the original and hotfix builds. For example, the two files list different Windows RVAs for the same input handler. The alpha is evidence of coverage, with release stability and local compatibility still separate questions. [RobTop's Steam announcements](https://store.steampowered.com/oldnews/?appgroupname=Geometry+Dash&appids=322170&feed=steam_community_announcements) · [Developer's iOS patch history](https://apps.apple.com/bn/app/geometry-dash/id625334537?platform=ipad) · [gdsolver Windows release](https://github.com/gdsolver/gdsolver/releases/tag/v0.6.1) · [Geode alpha release](https://github.com/geode-sdk/geode/releases/tag/v6.0.0-alpha.1) · [2.209 bindings](https://raw.githubusercontent.com/geode-sdk/bindings/main/bindings/2.209/GeometryDash.bro) · [2.2091 bindings](https://raw.githubusercontent.com/geode-sdk/bindings/main/bindings/2.2091/GeometryDash.bro)
- **Use the public bindings as research references with a custom runtime.** Identify the installed executable by SHA-256 and record the Steam build ID when available. Fingerprint any companion DLL whose entry points are used. Pin the binding commit, verify just the M1 surface on that binary (gameplay update boundary, jump press/release, full reset, live player pose/velocity), then expand by milestone. gdsolver reports that the two Windows executables share a displayed version string and checks the executable and companion DLLs before hooking. Verify that the frozen folder actually launches the pinned executable and use a separate save context. [gdsolver build checks](https://github.com/gdsolver/gdsolver#installing)
- **Treat functions and object layouts as separate compatibility work.** A unique signature can locate a function while its callers, input semantics, or member layout have changed. Some entries are virtual, inline, or incomplete. Favor verified RVAs and the smallest field surface for a known hash, with signatures as a porting aid. Check candidate identity and live semantics, including deterministic reset and input state across layer changes. Unknown builds or ambiguous/missing entries should leave the bridge inactive. If an essential entry is missing, time-box manual mapping for that entry on the exact executable, then report which capability is blocked. A Geode reference probe would be an optional fallback requiring a user decision.

### State-only observations and transfer

- **Treat the proposed vector as a partial observation.** Similar local geometry and y/vy can require different actions when a jump is buffered, a dash is active, an orb is spent, a group is about to toggle, or another player is airborne. Object velocity misses delayed moves, discontinuities, future spawns, and enable/disable events. Collision geometry can differ from sprite bounds or a generic oriented rectangle. Hidden hazards visible to the policy also make this a privileged-state benchmark. gdsolver documents rotated gameplay frames, subpixel landing phase, and moving groups that matter to replay. [Game trace and geometry evidence](https://github.com/gdsolver/gdsolver/blob/main/docs/ARCHITECTURE.md)
- **Start with a measured supported slice.** Use static cube terrain, hazards, and a few labeled interactions, then add modes against small authored diagnostic levels. Include actual velocity and gameplay orientation, held/buffered input, relevant contact/activation flags, and both bodies where dual is supported. Scope independent two-player controls separately since one shared bit cannot express two independent presses. Query collision-relevant geometry in gameplay coordinates, including current solidity/activation and actionable orb and portal parameters. Use a lookahead in time-to-contact with a bounded spatial window, stable identity for motion across consecutive samples, and explicit reporting of truncation or unsupported mechanics. Compare a sorted top-K feature vector with a masked pooled set encoder on the same drills and CPU budget. Add short history, selected trigger state, or recurrence when paired states with the same observation demonstrably lead to different transitions. Keep level IDs and absolute progress out of policy input. Split by layout family and include shifted and recombined drills to test transfer.

### Lockstep, action timing, and practice

- **Verify the game's tick boundary before choosing a hook.** Scheduler callbacks, input queue processing, collision/trigger updates, and render frames have different clocks. The 2.2091 bindings expose command processing with half/last-tick flags. gdsolver reports replay repeatability at fixed settings with click-on-steps, with observed collision differences across resolution settings. That supports a one-tick prototype. It leaves parity for this bridge, restart conditions, and throttling to measure. Apply input edges at a defined phase, advance exactly k completed physics ticks or stop on the first terminal tick, and return a post-step observation with an episode ID and tick. Keep game state access on the game thread, with the transport waiting separately. [2.2091 command and queue bindings](https://raw.githubusercontent.com/geode-sdk/bindings/main/bindings/2.2091/GeometryDash.bro) · [gdsolver determinism measurements](https://github.com/gdsolver/gdsolver/blob/main/docs/ARCHITECTURE.md)
- **Replace death-x as the sole acceptance test.** Replay the same tick-indexed tape at normal speed and under dedicated/background stepping. Compare per-tick position, velocity, mode, button/queue state, relevant trigger/activation events, and terminal event and tick. Report the first divergent tick. Repeat across visible and minimized runs, same-process full resets, and fresh launches with pinned settings and controlled seeds where available. Use a basic level, a timing-sensitive interaction, and a trigger-heavy fixture. Test that waiting for a command leaves physics frozen and that mode switches preserve the trace. Support k=1 in the harness from day one. For k=4, test the four possible decision phases with known-good inputs on the timing fixture. If four-tick control makes a section unreachable, use finer cadence or exclude it from that evaluation tier.
- **Keep both practice tools with distinct evidence requirements.** Start positions can create a useful synthetic drill distribution when preceding trigger state is irrelevant. Compare checkpoint suffixes against a continuous replay with the same input tape, including held input, dual state, moving objects, and pending triggers. gdsolver documents cases where native restoration needed extra state for buffered presses, dashes, and moving geometry. Use recorded prefix replay when restore parity fails, and measure reset cost. Count a completion only after a clean normal start from 0%. [Checkpoint restoration evidence](https://github.com/gdsolver/gdsolver/blob/main/docs/SECTION_SOLVE.md)

### CPU throughput and learning

- **Make 10× a measured target.** At 240 physics ticks/s and 60 decisions/s simulated, 10× means 2,400 ticks/s and 600 completed transitions/s, or roughly 1.67 ms per transition averaged over collection, resets, and learning if the target includes training. One million transitions at that rate take about 28 minutes, before any evaluation. First measure native replay with and without render suppression, then host round trips, then live observation extraction/encoding, then full PPO collection plus updates. Run on the target PC in both modes against a simple level and a dense, trigger-heavy one. Record sustained ticks/s and training transitions/s, median and p95 step latency, reset cost, and CPU/GPU use. For background mode, test minimized/unfocused runs and compare frame times of a representative foreground workload with training paused and active. A fast in-process replay elsewhere establishes feasibility for that design, with no measured estimate for this pipe and learner. [gdsolver architecture](https://github.com/gdsolver/gdsolver/blob/main/docs/ARCHITECTURE.md)
- **Profile before adding workers or attention.** If object scans dominate, cache static geometry and update dynamic geometry separately. If serialization dominates, test a compact fixed-width payload on the same replay before considering shared memory. Draw decimation can preserve parity where full suppression changes it. Scale to isolated instances only after measuring the single-instance limit and CPU contention. Base the initial sample budget on end-to-end wall time. SB3 PPO on CPU with a small feed-forward policy is a reasonable baseline. Compare it to a simple timing heuristic or behavior cloning from verified local replay tapes if exploration is slow. Use recurrence when history demonstrably helps, and defer custom PPO until a measured limitation requires it. Keep training code and transport out of the critical path for the native replay benchmark. [SB3 PPO and CPU guidance](https://stable-baselines3.readthedocs.io/en/master/modules/ppo.html)
- **Validate learning before building levelgen.** Build a small set of original, hand-authored editor drills covering jump timing, an orb, gravity or speed change, and moving geometry. Use a known-good tape for each. Add a seeded parameterized generator only when drill coverage is limiting, with examples checked for solvability at the chosen cadence. Treat Stereo Madness as a smoke test. Freeze the held-out revisions, seed protocol, initial model, and adaptation budget per comparison. Report first-run progress, capped full-run solve rate, attempts to first clear with failures accounted for at the cap, and practice cost in resets, simulated steps, and wall time. Reset the learner to its generation checkpoint before adapting to each held-out level. Use a separate validation pool for development decisions. Replace raw world Δx as the universal reward with verified level progress or explicitly limit the first reward to forward-only drills. Rotated or teleported sections can break the correspondence. [Rotated gameplay trace](https://github.com/gdsolver/gdsolver/blob/main/docs/ARCHITECTURE.md)

**Proposed milestone gates.** M0 identifies the build and maps the minimal bridge surface. M1 demonstrates tick-stamped input and reset on local, isolated play, with account writes and online submission prevented before automated completions. M2 establishes replay parity across modes and measures representative end-to-end throughput. M3 compares a small CPU baseline on authored drills and unseen variants. For practice and future cached online levels, verify isolation with separate saves and offline play after acquisition, including 2.209 death/play telemetry in the verification. [2.2091 automation telemetry precedent](https://github.com/gdsolver/gdsolver/releases/tag/v0.6.1)

## Response and revision — claude/plan-01, 2026-11-18T06:10Z

**Verification of the review's evidence:**
- Fetched `bindings/2.2091/GeometryDash.bro` (HTTP 200, about 1.4 MB). Its win RVA for `handleButton` is `0x33c5b0`, vs `0x339ac0` in `bindings/2.209`.
- The bindings repo commit log for that path shows activity on 2026-11-17/18.
- The Geode releases API lists v6.0.0-alpha.1 (11-01) and alpha.2 (11-15) as prereleases.
- The gdsolver repo exists.
- My earlier "no bindings/2.2091" statement was wrong. Corrected in Current facts.

**Accepted changes (revised in place above):**
1. Build identity by SHA-256 plus companion DLL fingerprints, a pinned bindings commit, and verified RVAs keyed by hash. Signatures are only a porting aid. The bridge stays inactive on unknown builds. Functions and layouts are verified separately. Mapping is minimal per milestone. Manual mapping is time-boxed, and a Geode probe needs a user decision. (Decision 7, M0.)
2. The observation is treated as partial and privileged:
   - Added actual velocity/orientation, buffered input, dash/orb/contact flags, per-body features, and collision-data geometry with activation state.
   - Stable IDs, a time-to-contact window, and truncation reporting.
   - No level ID or absolute progress as inputs.
   - Top-K vs set encoder compared head-to-head.
   - History/recurrence added only on evidence.
   - Start from a supported slice. (Decision 2.)
3. Lockstep: a verified tick boundary, input edges at a defined phase, exactly k ticks or stop at terminal, tick/episode stamps, game-thread-only state access, k=1 from day one, the k=4 phase test. (Decision 3.)
4. Death-x replaced by the per-tick trace parity suite across modes, window states, resets, and launches, on three fixtures, reporting the first divergent tick. (M2, Verification.)
5. Practice tools have separate evidence requirements, with prefix-replay fallback and reset cost measured. (Decision 5.)
6. 10× is a measured target: staged benchmarks, the listed metrics, background foreground-impact test, profile before optimizing or scaling. (M2.)
7. Reward is verified progress, with Δx only on forward-only drills. (Decision 4.)
8. Levelgen deferred. Original hand-authored drills with known-good tapes come first. Stereo Madness is a smoke test only. (M3/M5.)
9. Evaluation protocol frozen: a separate validation pool, a reset-to-checkpoint before each held-out adaptation, failures counted at the cap, practice cost reported. (Verification.)
10. Isolation (online submission, account writes, 2.209 telemetry) must exist before any automated completion; cached levels are played offline. (Decision 8, M1.)
11. Milestone gates M0–M3 adopted as proposed.

**Partially accepted:**
- Behavior cloning is accepted only from verified *auto-generated* tapes (heuristic or solver). The user explicitly did not pick learning from their own replays, so their tapes are not used unless they opt in.

**Rejected:** none. I found no claim in the review that the evidence contradicted.

**Points for round 2:**
- The custom runtime is kept even though Geode v6 alpha now supports 2.209x. That's the user's call, and they've been told. Please flag it if you think the prerelease state changes the risk enough to recommend Geode to the user.
- Please check that the revised Decisions 2, 3, 5, 7, 8 and M0–M3 reflect your review without distorting it.

## Review round 2 — codex/gd-review-02, 2026-11-18 UTC

**Agreed.** The revision addresses the round-one objections. The public 2.2091 bindings make a narrowly scoped custom bridge viable to investigate. Geode v6 remains a prerelease, and a reference probe remains a user-decided fallback if an essential mapping blocks M0. The exact-build and runtime checks still apply. [2.2091 Windows bindings](https://github.com/geode-sdk/bindings/blob/main/bindings/2.2091/GeometryDash.bro) · [Geode v6 alpha.2](https://github.com/geode-sdk/geode/releases/tag/v6.0.0-alpha.2)

- The revised observation design treats privileged state as partial and starts with supported fixtures. The cadence, replay parity, checkpoint fallback, isolation, and throughput gates reflect the review. The CPU baseline, authored drills, and frozen evaluation protocol are suitable first experiments. The restriction to verified auto-generated tapes for any behavior cloning reflects the user’s choice.
- The old question about whether the installed build is 2.2091 is stale. The local hash and Steam build are already confirmed above. M0 still verifies the frozen copy and the bridge’s minimal surface. M2 still measures parity and performance.
- **Replay storage estimate.** At 240 physics ticks per simulated second, packing the shared hold bit uses 1.8 kB per simulated minute, plus metadata. A compact diagnostic trace at an illustrative 32–64 bytes per tick uses about 0.46–0.92 MB per simulated minute before extra event data and compression. Keep verified input tapes with build, level revision, game settings, seed where applicable, and reset metadata. Keep detailed traces for parity fixtures and selected failures. Routine training can retain aggregate metrics and selected tapes. Reconstruct observations from tapes only where replay parity has been established.

## Decision

Status: agreed after round 2.
Agreed by: claude/plan-01 (proposer revision) and codex/gd-review-02 (review). The user approved the draft direction on 2026-11-17.
Decision date: 2026-11-18 UTC
Unresolved issues: No design objections remain. M0–M3 acceptance checks remain open.

## Implementation outline

No permanent role assignment. Allocate tasks based on current availability and overlapping edit paths. Order: M0 -> M1 -> M2 (these must be sequential); after M2, the Python side (obs/model/curriculum) and the mod side (practice/levelgen loading) can run in parallel with separate claims (`mod/**` vs `gdbot/**`).
