# Phase 3 presentation

A single HTML slide deck for the Phase 3 conversation, plus the [live demo script](demo-script.md).

[`index.html`](index.html) has inline CSS and JS, no fonts or scripts from the network, and loads the lab screenshots from [`../../screenshots/`](../../screenshots/) by relative path. It works offline, but only from inside this repository, because the screenshots are not copied into it.

## Open it

From the repository root:

```bash
open docs/presentation/index.html
```

Any current browser works. The slides are 16:9 and scale to the window. The URL hash tracks the slide (`index.html#7`), so a refresh or a bookmark keeps the position.

## Keyboard

| Key | Action |
|---|---|
| `→` `↓` `Space` `PageDown` | Next slide |
| `←` `↑` `PageUp` | Previous slide |
| `Home` / `End` | First / last slide |
| `N` | Show or hide the speaker notes for the current slide |
| `F` | Toggle fullscreen |

Each slide has 2 to 4 talking points in a hidden notes element. `N` opens them in a panel at the bottom of the window. Close it before sharing your screen, or share only the browser window and keep the notes on a second screen with a second copy of the page open.

## Print to PDF

1. Open the deck in Chrome, Edge or Safari.
2. Print (`Cmd+P`) and choose **Save as PDF**.
3. Set margins to **None** and turn on **Background graphics**.

Print CSS gives one 1280×720 slide per page (22 pages), with the speaker notes, the progress bar and the key hint left out.

## Slides

| # | Section | Slide |
|---|---|---|
| 1–2 | Intro | Title, the three phases |
| 3–10 | Phase 1 | Lab diagram, why this setup, how an event travels, what broke, reserved password, the agent is live, SSH brute force, real-time FIM |
| 11–20 | Phase 2 | The question, architecture, one brief, model vs. rules, coverage honesty, failure handling, working with AI, what review caught, the dev-only Agent SDK path, numbers |
| 21–22 | What's next | From slice to SaaS, with one more day, questions |

The Phase 1 slides only hold short, factual headlines. They should be aligned with `PHASE1.md` once it is written.
