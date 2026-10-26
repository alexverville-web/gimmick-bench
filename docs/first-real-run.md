# First real run: what to verify

The engine was written and unit-tested without access to After Effects or
Cinema 4D. The parts below depend on application behaviour that can only be
confirmed on a real machine. Run `python3 -m gimmick_bench run --quick` on one
Mac and one PC and check each item. Nothing here is assumed to work until it has.

## After Effects

- [ ] The build script runs (Mac: `osascript` + `DoScript`; Windows: `AfterFX.exe -r`) and AE quits afterwards.
- [ ] `~/GimmickBench/work/ae-*/manifest.json` has an empty `missing` list and no `expression_errors`.
      If not, note which match names or templates failed in that AE version and language.
- [ ] The render queue uses JPEG for processing comps, and real ProRes and H.264 for the exports (`render_queue[].format_actual`).
- [ ] aerender output contains "Starting composition" / "Finished composition", so `timing_method` is
      `start_finish_lines`. Check that `render_s` is close to aerender's own "Total Time Elapsed".
- [ ] Output lines arrive as they are printed (not all at the end). If they are buffered, `render_s`
      will be near zero or equal to the wall time, and we need another timer.
- [ ] The French interface (if any machine uses it) still finds the render settings templates.

## Cinema 4D

- [ ] c4dpy starts without a login prompt after the one-time Maxon App sign-in.
- [ ] `~/GimmickBench/work/c4d-*/manifest.json` has every scene and an empty `missing` list.
- [ ] Standard renderer renders through `RenderDocument` in c4dpy (with AO and GI effects present).
- [ ] On an Octane machine: whether `RenderDocument` drives Octane in c4dpy, or the Commandline fallback is used,
      and that the Commandline output contains "Rendering successful".
- [ ] Running c4dpy while the multitasking test also runs aerender does not hit a licence seat limit.

## Run as a whole

- [ ] A full run finishes in roughly 2 hours and a quick run in roughly 45 minutes. Adjust frame counts if not.
- [ ] Spread (CV) is under 3% on most tests when the same machine is run twice.
- [ ] The result reaches the Google Sheet.
