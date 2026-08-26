# ALC brand assets

## The mark

An open ring with a solid core. The ring does not close — the gap is where the
human stays, **on** the loop rather than in it — and the core is the Single
Mandate the loop is built around.

## Which file to use

| File | Use it for | Notes |
|---|---|---|
| `mark.svg` | inline in HTML/JSX | uses `currentColor`; **only works inline** |
| `mark-dark.svg` | `<img>` on a dark surface | colours baked in |
| `logo.svg` | mark + "ALC" lockup | |
| `logo-full.svg` | mark + name + expansion | README headers, presentations |
| `favicon.svg` | browser tab | carries its own `prefers-color-scheme` |
| `apple-touch-icon.png` | iOS home screen | 180×180, opaque background |
| `../og.png` | social preview | 1200×630 |

## The one trap

`mark.svg` uses `currentColor` so it inherits the surrounding text colour. That
works **only when the SVG is inline**. Loaded through `<img src="mark.svg">` the
file becomes an isolated document, `currentColor` resolves to the UA default —
black — and the mark disappears on a dark surface. This is not hypothetical: the
first render of these assets produced exactly that.

- Inline (React `Mark` component, or pasted `<svg>`): use `mark.svg`.
- `<img>`, README, anywhere you cannot inline: use `mark-dark.svg`, or a PNG.
- GitHub READMEs: use `<picture>` with both themes — see the repo root README.

## Rules

- **Minimum size 16px.** Below that the core closes up and it reads as a blob.
- **Clear space**: at least the width of the core on every side.
- The ring takes the text colour; the core may stay accent `#5794e6`, or take
  the same colour as the ring in single-colour contexts.
- Do not: rotate it, close the gap, add a gradient, put it on a busy photo, or
  recolour it to a hue outside the token set.

## Palette

Surfaces `#1b1d1f` `#212427` `#26292c`, border `#35393d`, text `#d5d8dc`
`#8b9096` `#7d848b`, accent `#5794e6`, status `#5cc975` `#d9a343` `#ee6f66`
`#c9a23f`. These are the app's tokens, unchanged — the site and the product are
meant to read as one instrument.
