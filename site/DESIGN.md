# jev-lint landing page — design brief

Surface: `site/index.html`, single static page, no build. Mode: Persuade (a
reader decides to install). Written 2026-09-18 before the rebuild; the page
is checked against this file, not against taste.

## Concept: the proof sheet

A linter for a personal wiki is an editor with a red pen. The page is that
editor's desk at night: a stack of note pages, one lifted so the contradiction
can be read against the page below it, a single correction line drawn across
the claim. Everything on the page is either evidence (quotes, numbers,
commands) or the rule that organizes it. Nothing decorative gets its own box.

Anti-references, named so a reviewer can call a choice wrong:

- not the dark SaaS template: no purple gradient, no glow blobs, no grid of
  icon cards, no Inter
- not a stationery shop: no ribbons, tape, coffee rings, skeuomorphic clips
- not a 3D showcase: the object supports the headline, it never competes with
  it, and text is always HTML, never baked into a render

## Palette

Light ("day desk"):

- paper `#efe7d8`, sheet `#f7f1e6`, ink `#20231f`, muted `#5c5e56`,
  rule `#bbb3a5`
- correction red `#a83d29` (findings, focus, selection)
- highlighter `#f2d15a` (one use: the matching line on the page under the
  lifted one, and the probability bar)

Dark ("lamp on"): paper `#1b1a17`, sheet `#232220`, ink `#ece6d8`,
muted `#a39d90`, rule `#3d3a34`, red `#e0705a`, highlighter `#e3c34f`.
Both follow `prefers-color-scheme`; no toggle (nothing to persist, no JS).

Red means "a finding or the thing you must look at". It is never used for
buttons, links in body text, or decoration. Highlighter marks exactly one
line per view.

## Type

- Literata (variable, optical size 7–72, weights 300–800, italic) for
  headlines and reading text. It was drawn for long-form screen reading
  (Google Play Books), so it reads as a wiki page, not a magazine.
- Courier Prime (400, 700) for commands, paths, probabilities, labels. A
  typewriter face on a paper page reads as the lint output itself: typed,
  provisional, correctable.
- Both self-hosted as latin woff2 subsets in `site/fonts/` (246 KB total),
  regular Literata and Courier Prime preloaded, italic swapped in late.
- Scale: h1 clamp(2.8rem, 5vw, 4.6rem) at weight 700 and opsz 72, letter
  spacing -0.03em, sized so "your second brain" holds one line from 840 px
  up (three-line headline); body 19px/1.55 at opsz 12; mono labels 12–13px
  uppercase with 0.06em tracking.

Retired: Newsreader and IBM Plex Mono (the previous page and the report).
Nothing on the landing page may reintroduce them.

## Layout

- One column of measure 60–66ch for reading; wide sections split 0.8fr/1.2fr
  with the evidence on the right.
- Hairline rules organize evidence. No cards with shadows except the lifted
  page and the finding card (which is itself a note page).
- Sections separated by rules, not by background changes, except the install
  section which inverts to ink.

## Motion rules

- One page-load reveal on the hero copy (translate 20px + blur 6px, 700 ms,
  `cubic-bezier(.16,1,.3,1)`). The hero object settles (translate 18px,
  rotate 1°) with no opacity change, so Chrome counts its first paint as LCP;
  fading it delayed LCP by 4.6 s in Lighthouse.
- Scroll reveals use CSS `animation-timeline: view()` only; browsers without
  it show static content. No IntersectionObserver, no scroll library.
- Hover: buttons lift 2px, links thicken underline. Focus: 3px red outline,
  4px offset, always visible.
- The finding card: click or Enter/Space toggles it open; the probability bar
  grows from 0 to 84% over 600 ms when opened. Hover over the closed card
  tints its header with the highlighter (a transform lift would be
  overridden by the filled `.rise` animation).
- Copy button: click copies the install line, label swaps to "copied" for
  1.5 s, no toast.
- `prefers-reduced-motion: reduce` removes every transform and duration; the
  page still works because none of the motion carries meaning.
- No parallax, no mouse-follow, no smooth-scroll library, no scroll jacking.

## 3D role

One hero object, rendered in Blender to transparent WebP: a short stack of
off-white note pages on the desk, the top page lifted at its corner as if a
hand just let go, a red correction line drawn across one sentence on it, the
same sentence visible on the page below in a slightly different wording. The
render is atmosphere and metaphor; the actual quotes live in HTML in the
finding card underneath. Two sizes (≤ 140 KB desktop, ≤ 70 KB mobile),
`fetchpriority=high`, explicit width/height so it counts as LCP without
layout shift. The render is the only image besides `paper.webp`.

If a second still is cheap, the closed stack is shown first and the lifted
one crossfades in with the reveal; no sprite sequence, no video, no three.js.

Provenance (as shipped): `site/hero_scene.py` rebuilds the scene from nothing
in Blender 5.2.1 (collection `JEV_HERO`; six pages, analytic corner curl on
the top page with bend start 0.014 m and radius 0.040 m, Solidify + Bevel,
marks drawn as UV masks in one Principled paper shader, three area lights,
no floor, film transparent). Rendered with Cycles on CPU at 2400×1800, 128
samples, Standard view transform (AgX greyed the red and yellow). Metal GPU
hangs in background mode on this Mac, hence CPU. Cropped to 1805×1451 and
encoded to `hero.webp` (1808 px, 47 KB) and `hero-sm.webp` (840 px, 18 KB).
No external assets, textures, or models. `og.jpg` (1200×630, 78 KB) is a
Playwright screenshot of the same render on the paper palette. Second still
not made: the one-still hero was already at the budget's quality bar.

## What stays still

Headline, numbers, quotes, the terminal transcript, the install block. A
reader who never moves the mouse must see everything worth seeing.

## Budget

First load under 600 KB (fonts 246 KB, hero ≤ 140 KB, paper.webp 20 KB,
HTML ≤ 25 KB). LCP under 2.5 s on a throttled mobile profile. No third-party
requests.

Measured 2026-09-18 (Lighthouse 13, simulated mobile, local server): 298 KiB
transferred, FCP 1.7 s, LCP 2.6 s (element render delay 162 ms; the rest is
simulated slow-4G font transfer), CLS 0.002, performance 96, accessibility
100, SEO 100.

## Choices made without the owner

- No light/dark toggle; the system setting decides.
- The finding card shows the real recorded contradiction from the 17
  September run (`wiki/concepts/compiled-vs-retrieved-knowledge.md:22` vs
  `wiki/concepts/llm-wiki-pattern.md:19`, Jev probability 0.84, quotes
  verbatim from `vault-run-final.json` on Core, line fragments included).
  The earlier invented Atlas/Amsterdam example was replaced after the review
  thread flagged it as looking like output. The tension phrases are
  highlighted; neither line is struck through, so the page never implies
  the tool judged which one is wrong.
- Highlighter band is translucent in dark mode (`--hl-band`) so cream text
  stays legible on it.
- Finding card has elevation only, no hairline border (impeccable detector
  flagged the pair); its own surface tone `--card` separates it from the
  sheet.
- Version "0.1.0" hidden from the nav under 800 px so the nav fits one line.
- `paper.webp` kept as the only texture; no Painter image was generated.
- Inline SVG favicon (page with a red line) instead of a favicon.ico request.

## Claims allowed on the page

99 pages, 1,267 Jev questions, 16 findings (2 contradictions, 1 stale, 1
missing page, 12 unresolved markers), 114 s, $0.024 input-token cost,
measured on the owner's own vault on 17 September 2026. Nothing else is
claimed. Copy states that agents wrote most of the code.
