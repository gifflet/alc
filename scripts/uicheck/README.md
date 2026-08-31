# uicheck — verifying the web IDE on real surfaces

Five small CDP tools that check the UI where it actually runs: a real desktop
Chrome, a real Android device, and emulated tablets. They exist because unit
tests cannot see layout — every defect these found (a table column pushed off
screen, a status dot squeezed to 4px, an editor left dark on a light page, a
chart with zero-height bars) passed the suite first.

They talk to Chrome's DevTools Protocol directly and depend only on `ws`, which
already ships in `ui/node_modules`.

## Connecting

**Desktop** — start a Chrome with the protocol open:

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --headless=new --remote-debugging-port=9333 \
  --user-data-dir=/tmp/uicheck-profile --window-size=1440,900 \
  "http://127.0.0.1:8642/projects/<id>/fleet"
```

**Android** — the device reaches the host over `adb reverse`, so `alc ui` can
stay bound to 127.0.0.1:

```bash
adb reverse tcp:8642 tcp:8642                      # device -> host
adb forward tcp:9222 localabstract:chrome_devtools_remote   # host -> device Chrome
adb shell svc power stayon usb                     # keep the screen awake
```

`CDP_PORT` selects which browser a tool drives: `9333` (desktop) or `9222`
(device). It defaults to 9222.

## Ports

`9333` is the desktop Chrome instance launched with `--remote-debugging-port=9333`.
`9222` is the connected Android device, forwarded from the device's Chrome via `adb forward tcp:9222 localabstract:chrome_devtools_remote`.

## The tools

| Tool | Answers |
|---|---|
| `sweep.mjs <base> <projectId> <fragment>` | does any route overflow, render empty, or log an error? |
| `verify.mjs <base> <projectId> <fragment> <desktop\|mobile>` | does each shipped move still hold on this surface? |
| `emulate.mjs <url> <w> <h> <touch:0\|1> <label>` | what layout and density does a given device resolve to? |
| `shot.mjs <out> [fragment]` | capture a PNG of the current page |
| `cdp.mjs "<expression>" [fragment]` | evaluate one expression in the page |

```bash
CDP_PORT=9333 node scripts/uicheck/sweep.mjs http://127.0.0.1:8642 my-proj-1a2b 8642
CDP_PORT=9222 node scripts/uicheck/verify.mjs http://localhost:8642 my-proj-1a2b 8642 mobile
CDP_PORT=9333 node scripts/uicheck/emulate.mjs "$URL" 810 1080 1 "iPad portrait"
```

`emulate.mjs` also honours two env vars: `PROBE` (an expression evaluated INSIDE
the emulation, before metrics are cleared) and `SHOT` (a path to capture to).

## Two notes worth keeping

**The overflow rule is deliberately narrow.** `sweep.mjs` flags a box whose
`scrollWidth` exceeds its `clientWidth` while `overflow-x` is `visible`, and
skips boxes with no content box at all. A broader rule ("ignore anything an
overflow ancestor contains") was tried and rejected: it silenced Monaco's
zero-width cursor layer, but it also silenced every real break in the
pre-refresh baseline. A detector that cannot fail a broken build is worse than
none — recalibrate against a known-bad revision before loosening it.

**Fixtures go stale.** A run log stops being "live" once it goes quiet past the
manifest timeout, so it leaves the Fleet by design. `touch` the run logs before a
run that expects units on screen, or you will chase a phantom failure.
