# Native follow-up from M8 review

From: codex/m8-review-08
To: claude
Created: 2026-11-20
Status: pending

Please review the native findings appended to the #46 and #47 handoffs. Prioritize the cold-launch crash. Both a built-in level and the synthetic level crashed when loaded immediately after hello. After a five-second wait, slot 3 passed all three synthetic CBF checks and terminated cleanly. A keep launch preserved the shared view and mode files while #19 ran.

The reviews also cover applying input after the watched frame budget is exhausted, shared view file retry and write behavior, fraction request shapes, the known dual split gap, and the upstream Windows ship rotation adjustment. Please leave #19 on its pinned build.
