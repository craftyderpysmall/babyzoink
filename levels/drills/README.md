# M3 drill fixtures

These are original layouts generated from the fixed seeds in [index.yaml](index.yaml). Each text file is the exact protocol v0 `level.data` payload. Pass it as a string with `kind: "level_string"` and a unique `name`. The SHA-256 covers the payload bytes with no trailing newline. To regenerate the set from the repo root, run `python -m gdbot.levels.drills`.

Every family has one training variant and one shifted or recombined held-out variant. The nominal duration uses the rightmost object and the measured 1x forward speed. The actual finish time and the speed-portal variant's duration will differ in game. The layouts only use forward movement, so the manifest marks horizontal progress as a valid reward.

A live completion tape is required before training or evaluation uses a drill. Entries with matching verified tapes have `training_ready: true` and a tape path relative to this directory. Tapes record a fixed wait at the end of the run so the game's wall-clock completion callback can fire while the simulation is paused. The moving-geometry fixtures require a bridge that observes trigger-moved objects.

## Serialized object IDs

| ID | Use in the drills | Source |
| ---: | --- | --- |
| 1 | Black Gradient Square, used as a solid block | [Object IDs](https://flowvix.github.io/gd-info-explorer/ids) |
| 8 | Black Gradient Spike, including the rotated ceiling hazard | [Object IDs](https://flowvix.github.io/gd-info-explorer/ids) |
| 10 | Blue Gravity Portal, restores normal gravity | [Portal definitions](https://gdpy.readthedocs.io/en/master/_modules/gd/api/enums.html) |
| 11 | Yellow Gravity Portal, reverses gravity | [Portal definitions](https://gdpy.readthedocs.io/en/master/_modules/gd/api/enums.html) |
| 36 | Yellow Jump Orb | [Object IDs](https://flowvix.github.io/gd-info-explorer/ids) |
| 202 | Fast speed portal | [Portal definitions](https://gdpy.readthedocs.io/en/master/_modules/gd/api/enums.html) |
| 901 | Move trigger, targets a grouped block | [Object IDs](https://flowvix.github.io/gd-info-explorer/ids) |

The header explicitly selects classic cube at normal speed and leaves the color channels at game defaults. Move trigger properties use keys `10` for duration, `29` for vertical offset, and `51` for target group. The target block uses `57` for group membership. [Header reference](https://github.com/gd-programming/gd.docs/blob/main/docs/resources/client/level-components/inner-level-string.md) · [Object property reference](https://github.com/gd-programming/gd.docs/blob/main/docs/resources/client/level-components/level-object.md) · [Editor Guide](https://www.robtopgames.com/files/GDEditor-ES.pdf)
