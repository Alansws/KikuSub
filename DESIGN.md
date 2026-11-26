---
name: KikuSub
description: A cue-script interface for a local Japanese subtitle workstation.
colors:
  canvas: "#FFFFFF"
  panel: "#F5F5F7"
  inspector: "#FBFBFD"
  sheet: "#FFFFFF"
  surface: "#FFFFFF"
  well: "#F2F2F7"
  ink: "#15191C"
  ink-2: "#4B4B52"
  ink-3: "#55555C"
  blue-pencil: "#295CE6"
  blue-pencil-text: "#2453D4"
  vermilion: "#B8412F"
  approved: "#356B52"
  attention: "#7E5416"
  hairline: "#E2E2E7"
  dark-stage: "#0C0C0E"
  dark-canvas: "#161618"
  dark-panel: "#1D1D1F"
  dark-surface: "#242427"
  dark-raise: "#313135"
  dark-well: "#121214"
  dark-ink: "#EDEDEF"
  dark-blue-pencil: "#3467EB"
  dark-blue-pencil-text: "#6B96FF"
  dark-vermilion: "#E5776A"
typography:
  display:
    fontFamily: "-apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Hiragino Sans', 'PingFang SC', sans-serif"
    fontSize: "22px"
    fontWeight: 620
    lineHeight: "30px"
    letterSpacing: "-0.022em"
  heading:
    fontFamily: "-apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Hiragino Sans', 'PingFang SC', sans-serif"
    fontSize: "15px"
    fontWeight: 600
    lineHeight: "22px"
    letterSpacing: "-0.005em"
  body:
    fontFamily: "-apple-system, BlinkMacSystemFont, 'SF Pro Text', 'PingFang SC', 'Hiragino Sans GB', sans-serif"
    fontSize: "13px"
    fontWeight: 400
    lineHeight: "19px"
    letterSpacing: "0"
  cue:
    fontFamily: "'Hiragino Sans', 'Hiragino Kaku Gothic ProN', 'SF Pro Text', 'PingFang SC', sans-serif"
    fontSize: "21px"
    fontWeight: 500
    lineHeight: "30px"
    letterSpacing: "0.01em"
  data:
    fontFamily: "'SF Mono', ui-monospace, SFMono-Regular, Menlo, monospace"
    fontSize: "11px"
    fontWeight: 400
    lineHeight: "16px"
    letterSpacing: "0.01em"
  label:
    fontFamily: "'SF Mono', ui-monospace, SFMono-Regular, Menlo, monospace"
    fontSize: "11px"
    fontWeight: 500
    lineHeight: "16px"
    letterSpacing: "0.07em"
rounded:
  xs: "3px"
  sm: "5px"
  md: "7px"
  lg: "10px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "24px"
  xxl: "32px"
components:
  button-primary:
    backgroundColor: "{colors.blue-pencil}"
    textColor: "#FFFFFF"
    rounded: "{rounded.sm}"
    padding: "0 12px"
    height: "28px"
  button-secondary:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink}"
    borderColor: "rgba(0, 0, 0, 0.14)"
    rounded: "{rounded.sm}"
    padding: "0 12px"
    height: "28px"
  button-soft:
    backgroundColor: "{colors.well}"
    textColor: "{colors.ink-2}"
    rounded: "{rounded.sm}"
    padding: "0 12px"
    height: "28px"
  option-block:
    backgroundColor: "{colors.well}"
    textColor: "{colors.ink}"
    rounded: "{rounded.sm}"
    padding: "8px 10px"
  button-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.ink-2}"
    rounded: "{rounded.sm}"
    padding: "0 12px"
    height: "28px"
  nav-item-active:
    backgroundColor: "rgba(41, 92, 230, 0.08)"
    textColor: "{colors.blue-pencil}"
    rounded: "{rounded.sm}"
    padding: "0 8px"
    height: "30px"
  cue-row:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink}"
    height: "30px"
  badge:
    backgroundColor: "rgba(21, 25, 28, 0.07)"
    textColor: "{colors.ink-2}"
    rounded: "{rounded.xs}"
    padding: "0 6px"
    height: "18px"
---

# Design System: KikuSub

## Overview

**Creative North Star: "The Cue Script"**

KikuSub is a working desk, not a dashboard. Its visual world is the **recording cue script**: a stack of pale paper cue sheets, a sumi-ink line, a blue pencil for the editor's marks, a vermilion brush for corrections, and a narrow margin where every cue is ticked off. The interface is the sheet; the film is the light source; the waveform is the optical soundtrack printed alongside the frames.

The system is deliberately quiet around the work. Three surfaces (canvas, panel, sheet) replace cards-in-cards. Hairlines replace heavy borders. One family of system type carries navigation, labels, body and Japanese cue text; monospace is reserved for time, counts and measurement. The only saturated color on a normal screen is the blue pencil; vermilion appears only when something needs the editor's attention.

Light is the daylight proofing desk; dark is the dubbing booth at night. The stage stays dark in both, because the film is the brightest object in the room. The app should feel at home beside Final Cut, Linear and IINA without borrowing any of their skins: those are the craft bar, not the world.

**Key Characteristics:**

- Paper, ink, blue pencil, vermilion. No gradients, no glass decoration, no card shadows.
- One type family, three voices: UI sans, Japanese cue sans, mono data.
- Dense where the work is dense; quiet where the work is quiet.
- A 44 px cue margin is the signature: status, navigation and proofreader's mark in one column.

## Colors

A **neutral** paper ground, a sumi ink, and two pencils. The palette is Restrained: one accent does the action, one signal does the correction, one green does approval.

**The Nobody's-Teal Rule (2026-11-26, third pass).** Every neutral in this system is a *pure*
neutral: R = G, and B sits at most three levels above them. The previous carbon ladder
(`#1A1C1F → #24272B → #2C3136`) and the previous chrome (`#F0F2F4`) both carried a blue-grey
cast, and stacked six deep that cast read as a haze over the whole window. Greys are now mixed
from `rgba(0,0,0,…)` in light and `rgba(255,255,255,…)` in dark, never from a tinted base.

### Primary

- **Blue Pencil — Studio royal cobalt.** Light: fill `#295CE6` (white text 5.57:1); text/icon
  `#2453D4` (6.44:1 on sheet, 5.91:1 on chrome); selected wash `rgba(41,92,230,0.08)`.
  Dark: fill `#3467EB` (white text 4.90:1, hover `#3B6DEE` at 4.56:1); text/icon `#6B96FF`
  (5.96:1 on chrome); selected wash `rgba(52,103,235,0.16)`.
  The 2026-11-25 value (`#0B63E5`) was a clean cobalt but read as **web link blue** next to a
  neutral grey; the royal cobalt sits deeper and leans indigo, which is what the blue controls in
  Final Cut's inspector do. The requested dark hover `#4274F2` measured 4.19:1 against white and
  was darkened 4 levels to `#3B6DEE` — the visually indistinguishable value that keeps white text
  legal. Text and fill are deliberately **two** tokens: a fill is read as a block, an 11 px icon
  or link is read as a glyph.
- **Vermilion** (`#B8412F`, 5.37:1; dark `#E07A66`, 5.84:1): correction, "needs review", the active cue mark, destructive text. Never used for a primary action.

### Neutral (light: the paper desk)

- **Canvas** (`#FFFFFF`): the working stage. In daylight the page itself is **paper white** —
  the desk, not a grey felt under white cards. Every page ground, the cue sheet and the inspector
  live on this value or one step off it.
- **Panel** (`#F5F5F7`): **window chrome only** — sidebar, titlebar, status bar, timeline dock.
  It is never a page-internal command bar or filter strip; those sit on `--canvas` and are
  separated by a 1 px hairline (see The Chrome Is Not a Page Toolbar Rule). Apple's pure neutral
  light grey. The previous `#F0F2F4` was a blue-leaning industrial grey that contaminated the
  cobalt sitting next to it.
- **Inspector** (`#FBFBFD`, `--bg-inspector`): the third plane, half a step between paper and
  chrome. Three adjacent planes (sidebar / work / inspector) are each separable by value alone.
- **Sheet / Surface** (`#FFFFFF`): the cue table, fields, popovers. Separated from the paper
  ground by a 1 px `--rule`, never by a grey wash.
- **Well** (`#F2F2F7`, `--well`): the **recessed** fill for unselected option blocks, info strips,
  inputs, slider grooves and tag slots. In light it sits one step *below* the paper; in dark it
  sits one step *below* the canvas (`#121214`). Hover is `--well-hover`, selection adds the blue
  pencil. **A well never lifts.** Lifting it was the 2026-11-25 mistake: six raised wells per
  screen is exactly what "washed-out grey fog" looks like.
- **Well line** (`rgba(0,0,0,0.14)` light / `rgba(255,255,255,0.13)` dark, `--well-line`): the
  1 px edge of a **box-shaped recess** — `<select>`, `<input>`, `<textarea>`, `.field`, `.ai-input`.
  It may never be `transparent`: `#F2F2F7` on `#F5F5F7` differs by two levels, so without the
  edge a dropdown collapses into a floating chevron. Blocks (`--well` option groups) still rely
  on value alone; only fields carry the edge.
- **Sumi** (`#15191C`; dark `#EDEDEF`): primary text, 16.2:1 / 14.4:1 on chrome.
- **Graphite** (`#4B4B52`; dark `#B9B9BF`): secondary text, 7.1:1 / 8.6:1.
- **Slate** (`#55555C`; dark `#A0A0A6`): 11 px labels, counts and units; 5.8:1 / 6.5:1 on the
  panel, 4.7:1 on the raised layer. 11 px is the floor, so this value may not go lighter.
- **Hairline** (`#E2E2E7` rule, `rgba(0,0,0,0.13)` line; dark `#303034` /
  `rgba(255,255,255,0.13)`): 1 px rules. No 5 % grey separators, no tinted greys.

### Neutral (dark: the carbon console)

Five steps of **pure neutral** carbon, borrowed from the grading bay rather than from "black mode".
Values are deliberately **not** near-black except the stage: a charcoal room reads professional and
lets the film be the only bright thing on screen. Every step is neutral to within three levels of
blue, so six stacked surfaces never add up to a haze.

- **Stage** (`#0C0C0E`, `--stage-bg`): the room around the picture. The darkest value in the app,
  and the only one that is near-black.
- **Canvas** (`#161618`): the working ground, one step up from the stage.
- **Panel** (`#1D1D1F`): chrome — sidebar, titlebar, status bar, **inspector**.
- **Surface** (`#242427`): panels, the cue table, cards laid on a page.
- **Raise** (`#313135`, hover `#3A3A3F`): buttons, popovers, dialogs — the only layer that is
  "on top". It carries a `inset 0 1px 0 rgba(255,255,255,0.06)` top highlight and a `#0E0E10`
  seam instead of a large shadow.
- **Well** (`#121214` + `rgba(255,255,255,0.07)` hairline): input fields, slider grooves, tag
  slots, and any recessed block. It sinks **below the canvas** — the same direction as in light.
  This is Final Cut's control grammar: a groove is darker than what surrounds it, a key is lighter.

**Why the direction is fixed.** The 2026-11-25 pass made the dark well *lift* by 6.5 % white
"because FCP's controls look lighter". That is true of FCP's **buttons**, not of its **grooves**;
applying it to every well put six light patches on every screen, and the result was reported as
"a washed-out grey-teal fog floating above the surface". The two roles are now two tokens:
`--raise` lifts, `--well` sinks, and `--surface` sits between them.

### Named Rules

**The One Colour One Job Rule.** Blue means "you can act / this is selected / this is a proposal". Vermilion means "this is a correction or needs attention". Green means "approved / passed". A color never carries a status alone; a word, a mark or an icon travels with it.

**The Dark Is a Room Rule.** Dark is not the light theme inverted. It is the dubbing booth: a
five-step carbon ladder (stage → canvas → panel → surface → raise), neutral near-white text (not
paper-warm — the warmth was part of the haze), the film still as the brightest plane. Both
appearances are audited at 4.5:1 for body text and 3:1 for large text.

**The Raise Lifts, the Well Sinks Rule (2026-11-26).** In both appearances, `--raise` is lighter
than what it sits on and `--well` is darker. The direction never flips between appearances:
a groove is a groove. `verify_phase2_shell.mjs` asserts the luminance sign in both themes, so a
future "dark wells should lift" experiment fails on the spot instead of shipping.

**The No White Frame Rule (2026-11-26).** A white surface may only be a **sheet, a field or a
popover**. Anything that is *a section of a page* — an option group, an info strip, a mode card,
a settings group, an empty state — is either a **title + a hairline** or a **well**. Never a white
card on a grey ground, never a white frame inside a white frame, never a bordered box used as a
section. On the dark side the same rule reads: a card is a carbon step, not a lighter box with a border.

**The Chrome Is Not a Page Toolbar Rule (2026-11-26).** `--paper` belongs to the window shell —
sidebar, titlebar, status bar, timeline dock. A **page-internal** command bar, filter strip or
paste area (the three AI workbenches, export filters, settings toolbars) sits directly on
`--canvas` and is separated by a 1 px hairline. Never stack a page ground, a grey command bar and
a white table on top of each other: that is the "grey ground with white-framed buttons" pattern
the user experiences as three dirty bands. Secondary buttons are paper-white (`--raise`) with a
1 px `--well-line` edge, or a borderless `--well` soft fill; they are never white keys on a grey strip.

**The Two-State Switch Rule (2026-11-26).** A switch in the chrome answers *"what happens if I
press it"* in one press. The appearance button flips light ⇄ dark directly; `auto` (follow the
system) is a Settings choice, never a third stop in a toolbar cycle. A two-state control that needs
two presses to reach the other state is a three-state control in disguise.

### Palettes: one base, six skins (2026-11-26, Batch 3)

Colour now has **two orthogonal axes**, and neither is a component branch:

| Axis | Attribute | Values | Answers |
| --- | --- | --- | --- |
| Light / dark | `html[data-theme]` | `light` \| `dark` (resolved from `auto` / `light` / `dark`) | Which room am I in? |
| Palette | `html[data-palette]` | `cobalt` \| `nord` \| `rose-pine` \| `everforest` \| `catppuccin` \| `cinema-amber` | Which base colours is this room painted in? |

`cobalt` is the default and is **exactly** the Stage 1 palette; it costs no extra CSS
block because it lives in `:root` (light) and `html[data-theme='dark']`. The other five
palettes add **two blocks each** — `html[data-palette='<id>'][data-theme='light']` and
`…[data-theme='dark']` — and only override **base colours** (canvas / paper / surface /
raise / well / ink / rule / accent). Everything derived is computed once with
`color-mix(in srgb, var(…))`, including:

- window chrome: `--bg-toolbar / --bg-status / --bg-sidebar` mix `--paper` with transparency;
- hairlines and washes: `--line / --line-2 / --fill / --row-hover / --well-line /
  --cue-lane / --cue-wash / --cue-block` mix a neutral ink with alpha;
- accent-derived washes: `--accent-soft / --accent-ring / --accent-line /
  --cue-block-active / --cue-edge / --meter-a` read the **current** `--accent` or
  `--accent-text`;
- recess focus: `--well-focus` is the paper layer in light and a 4 % lift of `--well` in dark;
- stage: `--stage-bg` is the palette's dark stage in dark, and a `canvas → ink`
  mix in light (a room, not a second black band).

There is **no hardcoded `rgba(245,245,247,…)` / `rgba(29,29,31,…)`** left in the token
layer. A new palette is a CSS block pair plus one registry entry in
`desktop/renderer/src/lib/themes.ts`; components never read `data-theme` or `data-palette`.

#### The six palettes

| id | Name | Light signature | Dark signature |
| --- | --- | --- | --- |
| `cobalt` | 皇家钴蓝 | paper white `#FFF` / chrome `#F5F5F7` / cobalt `#295CE6` | carbon `#161618 → #1D1D1F → #242427 → #313135` / `#3467EB` |
| `nord` | 北欧极夜 | Snow Storm `#F7F9FC` / `#ECEFF4` / `#E5E9F0` / steel blue `#456E9E` | Polar Night `#242933 → #2E3440 → #353C4A → #434C5E` / `#4772A6` |
| `rose-pine` | 玫瑰松木 | Dawn `#FFFAF3` / `#FAF4ED` / `#F2E9E1` / pine `#286983` | Main `#191724 → #1F1D2E → #26233A → #312D48` / `#31748F`, text `#9CCFD8` |
| `everforest` | 暮森护眼 | warm paper `#FCF8EC` / `#F3EAD3` / `#EAE0C5` / forest `#277355` | `#1E2428 → #272E33 → #2E373C → #374248` / `#2B7E5E`, text `#83C092` |
| `catppuccin` | 拿铁与摩卡 | Latte `#F7F8FC` / `#EFF1F5` / `#E6E9EF` / `#1E66F5` | Mocha `#181825 → #1E1E2E → #26273A → #313244` / `#3B6CE2`, text `#89B4FA` |
| `cinema-amber` | 暗房琥珀 | `#FCFBF7` / `#F4F1EA` / `#ECE7DD` / amber `#B45309` | `#141413 → #1B1B19 → #232320 → #2E2E2A` / `#B8590C`, text `#F59E0B` |

Full primitives (including well / ink-2 / ink-3 / rule / danger / inspector) live in
`app.css`; the registry in `themes.ts` carries the subset the six cards draw. The two are
reconciled by `desktop/test/theme-preview.test.mjs`.

#### The Controls Must Survive Any Paper Rule

A palette is not allowed to make a control disappear. `--well-line` is
`color-mix(in srgb, neutral-wash 14%, transparent)` in light and `13%` in dark, so a
dropdown / number field / textarea always has a visible 1 px edge on every one of the
twelve combinations. **`transparent` is still forbidden.** The same rule covers the
secondary button (`--btn-line`), the 1 px `--rule` hairlines, and the focus ring
(`--accent-ring`).

#### Calibration notes (deviations from the supplied values)

All six palettes were measured in the real renderer across 6 × 2 = 12 combinations.
Two kinds of 1–3 level adjustments were needed; everything else is the supplied value:

| Where | Supplied | Shipped | Why |
| --- | --- | --- | --- |
| `catppuccin` light `--accent-text` | `#1E66F5` | `#1B61E8` | 4.34:1 on `--paper` (11 px labels need 4.5); new value 4.74:1 |
| `catppuccin` dark `--accent-hover` | `#4273EB` | `#3D6DE4` | white button text 4.30:1 → 4.66:1 |
| `rose-pine` dark `--accent-hover` | `#3982A0` | `#357C99` | white button text 4.31:1 → 4.67:1 |
| `everforest` dark `--accent-hover` | `#318A68` | `#2F8163` | white button text 4.23:1 → 4.73:1 |
| `cinema-amber` dark `--accent-hover` | `#C66310` | `#B95D0E` | white button text 4.04:1 → 4.53:1 |
| `nord` / `everforest` dark `--danger` | default `#E5776A` | `#ED8F84` | 4.27 / 4.15:1 on `--surface` → 4.66 / 4.76:1 |

`rose-pine` light body text is 6.66:1 (above the 4.5:1 requirement, below the cobalt
7:1 AAA gate). The supplied `--ink #575279` was kept rather than darkened; cobalt keeps its
own 7:1 assertion. The light palettes intentionally do **not** make `--raise` brighter than
`--surface` (the supplied values make them equal, or in Rose Pine's case one level apart):
in daylight the paper desk is the highest value, and the invariant that matters is
**well sinks below canvas** in both modes, while dark keeps **raise > surface > canvas**.

### Appearance and the cue face

Appearance is **not** the whole theme. It is one preference with three values — `auto` (follow the
system, the default), `light` (daylight proofing), `dark` (dubbing booth) — plus two orthogonal
preferences: the **interface palette** (six base-colour skins, §Palettes) and the **cue font**:
`sans` (Hiragino Sans, default) or `mincho` (Hiragino Mincho).

The preference lives in **Settings → 外观**; the titlebar button and `⇧⌘A` are a **two-state
switch** (现在 ⇄ 另一面), resolved from what is on screen. So under `auto` + a light system, one
press still lands on dark (it writes the explicit `dark` preference). `auto` is never a stop in
that button's cycle.

- `html[data-theme]` carries only the **resolved** value, `light` or `dark`. There is no third
  colour world; `html[data-palette]` carries the skin, and mincho changes `--font-cue` and
  nothing else. The palette preference lives in `localStorage['kikusub.palette']`, inside the
  build's own `--user-data-dir` — never in a shared config file.
- Following the system is the HIG-correct default (`dark-mode.md › Best practices`: avoid an
  app-specific appearance setting). The manual override exists because this tool is used at night
  for hours; it lives in Settings, not as a permanent toolbar switch.
- The cue face is a reading preference, not a theme. A user may keep mincho in daylight proofing
  and switch to sans at 2 a.m. without touching the palette.

## Typography

**Display Font:** SF Pro / system sans (with PingFang SC, Hiragino Sans)
**Body Font:** SF Pro / system sans (with PingFang SC)
**Cue Font (sans):** Hiragino Sans → Hiragino Kaku Gothic ProN → SF Pro Text → PingFang SC
**Cue Font (mincho):** Hiragino Mincho ProN → Yu Mincho → Noto Serif JP → Songti SC
**Label/Mono Font:** SF Mono (with ui-monospace, Menlo)

**Character:** The voice is the macOS system voice, tuned like a printed cue sheet: tight display tracking, quiet body, Japanese set in Hiragino, and timecodes in tabular mono. No display face, no handwriting font, no type as costume.

**The Japanese Face Comes First Rule.** The cue face puts Hiragino ahead of PingFang SC even in
the `sans` preference. PingFang's kana and many kanji are drawn on a Chinese skeleton (「直」「骨」
「步」 visibly differ); a Japanese cue sheet has to keep the Japanese glyphs. Chinese text is still
covered by the PingFang fallback further down the stack, so no per-language font switch is needed.

### Hierarchy

- **Display** (620, 22/30, -0.022em): page titles and the one number that owns a screen.
- **Heading** (600, 15/22, -0.005em): section headings, inspector section titles.
- **Body** (400, 13/19): controls, prose, table translation. Maximum measure 75ch where prose runs.
- **Cue** (500, 21/30, 0.01em): the current Japanese line in the inspector; 13/20 in the table.
- **Data** (400, 11/16, tabular-nums): timecodes, durations, counts, zoom, frame rate.
- **Label** (500, 11/16, 0.07em, uppercase): column headings, stage labels, keyboard hints.

### Named Rules

**The Timecode Is Data Rule.** Every number that a user compares vertically or horizontally is tabular mono. No proportional figures in the table, transport or inspector.

**The No Display Face Rule.** Navigation, labels and buttons use the same system family as body. Identity comes from spacing, color and the cue margin, not from a decorative face.

## Layout

The window is a single 1360×838 working surface (minimum 1080×680). The titlebar is 44 px, the status bar 24 px, the sidebar 232 px (collapsed 52 px), the review inspector **348 px** — a full-height column, not a row. The review screen is a **full-bleed stage band** (the film, 16:9, capped at 640 px wide) over a **timeline dock** (single-row transport, ruler, waveform, cue lane, cue table), all inside the content column beside the inspector.

The 388 px in the Step 1 comp belonged to a **stage-row** layout (video and inspector side by side, table full width). The shell that shipped keeps the inspector as a column, so the table would lose 40 px of Japanese text for it — at the 1080 px minimum that is the difference between 164 px and 124 px of cue text. The width stays 348 until the stage-row layout itself is evaluated.

All three zones of the timeline dock share **one 16 px gutter** — transport, waveform and cue sheet start on the same left edge, and the outer frame padding is spent only once.

Single-column pages share **one** measure, `--measure-page` (**1040 px**), and it is **centred**
(`margin-inline: auto` / `justify-content: center`) inside whatever stage the window gives them:
import, export, prompt library, settings, task report. Centring is what keeps the visual centre of
gravity in the middle at large window sizes — a 1040 column pinned to the left edge leaves a slab
of empty paper on the right that reads as an unfinished layout. Because the measure is shared, all
of these pages still start on the same left edge at a given window width; nobody invents 1120 /
1000 / 960 again.

The import page keeps its own narrower measure (`--measure-card`, **760 px**), because the job
there is to choose a file, not to read a form — but it is centred on the same axis.

**The Import Page Has One Sheet Rule (2026-11-26).** With a project already open, the import page
contains exactly **one sheet**: the "continue this project" card (`--surface` + 1 px `--rule`),
because it carries both "where I left off" and the page's only primary button. Everything else on
the page is a **title + a hairline + rows on the ground** — never a second grey slab. The page used
to stack four full-width grey bars (continue card / "switch film" strip / export folder / recent
list) and read as bricks on white. The redundant "switch film" strip and its five extension pills
are gone: switching film has three paths already (the card's own "换片…" button, drag-and-drop
anywhere in the window, `⌘O`), so one 12 px sentence under the card is all the page says about it.

The transcribe page is the one two-column page: a 1120 px measure with a 320 px right rail for
"what happens next", also centred. Full-bleed grids (review console, the three AI tables) are the
documented exception: they stretch, because their job is dense data, not prose; they only share
the 24 px page gutter so their left edge matches the other pages.

Spacing follows 4 / 8 / 12 / 16 / 24 / 32. Controls are 24 (inline), 28 (default), 32 (large), 36 (primary). Table rows are 30 px (60 px when bilingual), the cue lane is **17 px** (11 px blocks), the waveform is **80 px** (drag the handle; 72–300 px, remembered per machine). Groups are tight; sections are separated by 1 px hairlines and 16–24 px of air.

The page skeleton is fixed: **titlebar → sidebar → page header → content → status bar**. No page invents its own header height or left edge. The four navigation groups are stages, not eight equal steps.

## Elevation & Depth

Flat by default. Depth is **tonal, not shadowed**, and it has two directions:

- **Light** reads as a sheet of paper: the paper desk (`--canvas`, white) is the highest value, the
  chrome (`--paper`) sits one step below it, and anything *inside* the page is a **recess** (`--well`,
  darker than the paper). Nothing in a light page is "on top of" the page.
- **Dark** reads as a panel in a grading bay: the film room (`--stage-bg`) is the floor, then
  canvas → panel → surface → raise, each one step up. Anything **recessed** inside a page
  (`--well`, inputs, grooves, slots) goes *down* below the canvas, exactly as in light.

The only shadows are the video frame (a physical screen in a dark room), true popovers/menus, and
the selected segment of a segmented control (a native control lift, not a card). Cards do not cast
shadows; a card is a sheet with a hairline or a tonal block, not a floating box.

### Shadow Vocabulary

- **Viewer** (`0 0 0 1px rgba(255,255,255,.08), 0 18px 40px rgba(0,0,0,.45)`): the film frame only.
- **Popover** (`0 12px 32px rgba(0,0,0,.45), 0 1px 0 rgba(255,255,255,.04) inset`): menus, command palettes, true overlays.
- **Thumb** (`0 1px 2px rgba(15,23,30,.12), 0 0 0 .5px rgba(15,23,30,.10)`; dark `0 1px 2px rgba(0,0,0,.42), 0 0 0 .5px rgba(0,0,0,.38)`): the selected segment only — the macOS standard white raised capsule, never a card shadow.

### Named Rules

**The Flat-By-Default Rule.** If a surface needs a shadow to be understood, the hierarchy is wrong. Fix the surface first.

## Shapes

Corners are small and functional: 3 px for badges and marks, 5 px for controls, 7 px for panels and cue sheets, 10 px for the window/viewer. Nothing is pill-shaped except status chips. Borders are 1 px hairlines; the only 2 px lines are the playhead and the active cue margin mark.

The cue margin is the recurring geometry: 44 px wide, separated by a 1 px rule, with a 12 px mark centered and a 2 px vermilion line on the active row. It is a margin, not a card.

## Components

### Buttons

- **Shape:** 5 px radius, 28 px default height; 24 px inline, 32 px large, 36 px primary.
- **Primary:** blue pencil fill, white text, no border, no bevel, one per view.
- **Secondary:** `--raise` fill (paper white in light, `#313135` in dark) with a **1 px
  `--well-line`** edge (`rgba(0,0,0,0.14)` / `rgba(255,255,255,0.13)`), ink text; in dark it also
  carries an `inset 0 1px 0` top highlight. A white key needs a visible edge on a white page.
  Buttons lift; that is the one place the dark theme goes *up*.
- **Soft (tinted secondary, 2026-11-26):** `--well` fill (sunk), no border, no bevel, graphite
  text, hover `--well-hover`. This is the button for a **secondary action that lives on its own** — "去双语翻译"
  inside a notice strip, "管理引擎…" at the end of a list, page-header actions. A lone bare blue
  word floating at the end of a row is not an action, it is a rumour.
- **Ghost:** transparent, graphite text; hover raises to the hover wash. Reserved for icon
  buttons in chrome and for actions already grouped with a visible parent.
- **Danger:** vermilion text only, isolated by 16 px and a hairline; never adjacent to a primary action.

### Segmented control

- **Shape:** 28 px track with 2 px inset; the selected segment is a **pure-white raised capsule**
  with a 0.5 px ring, a 1 px soft shadow and ink text — the macOS standard, not a blue-tinted slot.
- **Rule:** the track is a neutral wash. Blue is reserved for the primary action, radio dots and
  the single most important indicator; a selected segment is distinguished by elevation and ink,
  not by a translucent blue fill.

### Navigation

- **Shape:** 232 px sidebar; 30 px rows; 5 px radius.
- **Active:** blue-pencil tint plus a 1 px blue-pencil border; icon and label take the accent. No one-sided bar.
- **Groups:** four stages (`01 准备`, `02 核对`, `03 原文`, `04 交付`); counts on the right; keyboard hints on hover.
- **Rule:** no more than two levels; critical actions never at the bottom of the sidebar.

### Option blocks (wells)

- **Shape:** 5 px radius, `--well` fill (**sunk**, in both appearances), **no border**.
  Hover `--well-hover`. Selected adds a 1 px `--accent-line` ring plus `--accent-soft`;
  hover never changes a border.
- **Exception — text fields and dropdowns** carry `1 px solid var(--well-line)`:
  `rgba(0,0,0,0.14)` in light, `rgba(255,255,255,0.13)` in dark. A *block* is read from value
  alone; a *field* also needs an edge to say "there is a caret in here". `transparent` is forbidden
  — a field must be readable as a shape on both `--paper` and `--canvas`. Focus moves the fill to
  `--well-focus` (paper white in light), never up to `--raise`: raising a field would put it on
  the same layer as the buttons beside it.
- **Rule:** one interactive layer. An option group is not a card, and never sits inside another
  outlined box. Explain the option in 13/19 `--ink-2`, never in a second tonal block.
- **Where:** export mode / subtitle style / bitrate presets, engine rows, appearance and cue-font
  previews, prompt templates, settings groups, empty states.

### Cue table

- **Shape:** a cue sheet (`.cue-sheet`: `--surface` + 1 px `--rule`, 7 px radius) inset 16 px from the dock; 30 px rows (60 px bilingual); columns `44 px margin | start | end | duration | cue text | row actions`.
- **Cue margin:** 44 px, separated by a 1 px rule. Marks and the cue number both live in it: **approved** = 11 px check (green); **needs review** = 5 px vermilion dot; **machine-written line** = 10 px blue pencil. One mark per row, priority needs-review → approved → pencil.
  - The pencil means "this line already has a translation". It is drawn **only in 原文 mode**: in bilingual or target mode the translation is already on the sheet, so a pencil on every row is a stamp, not information.
  - The active row (selected row, or the block under the playhead) carries a 2 px vermilion line on the margin's left edge and a vermilion number. Hover wash, selected tint, find-hit wash and skipped-hit strike stay as they were.
- **Type:** Japanese 15/20 (13/20 at the minimum window), Chinese 12/16, timecodes **11 mono tabular**, headers 11 px labels (never the cue face, never ink).
- **Rule:** the table is the product; do not hide it behind cards, tabs or a drawer.

### Inspector

- **Shape:** 348 px panel on the third plane (`--bg-inspector`), 42 px tabs, hairline sections;
  no nested cards. Panels *inside* it (the 朗读 settings, AI proposal blocks) are wells, never
  white frames: a white frame inside a grey inspector is the card-in-card mistake in miniature.
- **Disclosure panels:** one header line (state chip + a single quiet "收起"), then the controls.
  No repeated title (the trigger already says what this is), no second close affordance, and the
  action row is an **even grid that fills the panel width** — never a row of buttons left-aligned
  under a half-empty line.
- **Tabs:** the selected tab is ink + a 2 px blue-pencil rule under it — not a tinted pill. The segmented control (原文 / 译文 / 双语) is the only control that uses the white raised capsule, so the two never read as the same thing. Counts in tabs are tabular numbers, not filled badges — **with one deliberate exception (2026-11-26):** the QA pending count (`质检待核 4`) is not a read-out, it is "four lines still need your hand", the same fact the cue margin's vermilion dot carries. So it is a vermilion micro-capsule (11 px tabular figures on `--danger-soft`, an inset 1 px vermilion ring at 24 %, 15 px tall, 8 px radius); it is omitted at zero. The chapter count stays a plain tabular read-out, which is what keeps the two from reading as the same signal.
- **Current cue:** 21/30-scale Japanese field on sheet white with a blue focus ring; 13/19 Chinese; one primary "update this line".
- **A/B:** two aligned rows, full text, one "use B" action below; section CTAs are secondary (paper + hairline). Never a second competing primary.
- **Danger:** delete sits alone at the bottom, after 16 px of air and a hairline.
- **No repeated read-outs:** device, engine, cue count, character count and resolution live in the titlebar and status bar; transcription parameters and version live in the task report. The inspector never restates them.

### Page note (AI pages)

The three AI pages carry one line under the title bar: a small line icon, one sentence stating
whether **this page can move the time axis**, and at most one link to the sibling page
(`锁轴润色 ①` ⇄ `重排润色 ②`, `双语翻译` → review console). It sits between the title row and the
command row, so it never moves when switching pages. This is a sentence, not an eyebrow: it names
a fact the user is about to act on.

### Empty states

One icon, one sentence naming the next action, one primary button, one quiet alternative. No
illustration, no marketing copy.

### Progress

Determinate progress is a solid cobalt fill on a neutral track — no shimmer, no gradient, no halo;
the bar is already moving. Indeterminate progress is a fixed block that breathes in opacity; it
never travels sideways, because lateral motion reads as "some progress is happening" and competes
with the content. `prefers-reduced-motion` stops both.

## Do's and Don'ts

### Do

- Keep the film still the brightest object on the review screen.
- Let the page ground be the paper and the blocks be recesses: value does the grouping, hairlines
  do the separating.
- Centre a single-column page with the shared 1040 measure; balance the air on both sides.
- Give a lone secondary action a soft button; put the wording at the action, not at the row end.
- Cut circled ordinals, stacked close buttons and repeated titles on first sight. If two elements
  say "close", delete one.
- Put the next action in the page, in the right rail or at the end of the task.
- Use the cue margin for status; use words and marks, not color alone.
- Keep timecodes, durations and counts in tabular mono.
- Test both appearances at 1360×838 and 1080×680.
- Keep the 44 px margin, 30 px rows and 1 px hairlines consistent across pages.
- Let a mark exist only where the fact is invisible elsewhere (that is why the pencil hides in bilingual mode).
- Say once per screen when a fact can be acted on from one place (the missing translation track is stated once, at the page top).

### Don't

- Don't nest cards or use a card as a page section.
- Don't put a white block on a non-white ground, or a white frame inside a white frame. That is
  the single most expensive tell of a layout that was assembled rather than designed.
- Don't leave a lone blue text link at the end of a row (or at the right edge of a page) in place
  of a control the user can see and aim at.
- Don't make a chrome switch cycle through three states; two states, resolved from what is shown.
- Don't use a 5% grey separator or a one-sided border on a rounded box.
- Don't put a primary action in a bottom bar; the status bar is read-only.
- Don't use a display face, gradient text or decorative glass.
- Don't make the interface the hero; the film and the cues are the hero.
- Don't reorder ⌘1–⌘8 without updating the menu bar, the shortcut help and the tests.
- Don't use looped decoration on anything that already moves (progress, playback). No shimmer, no stripes, no traveling highlight.
- Don't give settings categories their own hues; categories are learned by name and position, and the only saturated colour on a working screen is the blue pencil.

## Notes on Implementation

The high-fidelity prototype lives in `.impeccable/prototype/` (workspace root, not shipped). It is static HTML/CSS/JS, rendered through headless Chrome because the real app must not open a window. The production implementation must:
- keep the `html[data-theme]` token mechanism with exactly **two** appearances — light (daylight proofing) and dark (dubbing booth) — resolved from the `auto` / `light` / `dark` preference; `html[data-palette]` is a second, orthogonal axis (six base-colour skins, default `cobalt`), and mincho is `html[data-cue-font='mincho']`, a cue face on the same palette, never a third colour world;
- derived tokens are computed with `color-mix(in srgb, var(…))`; adding a palette means two `[data-palette][data-theme]` blocks plus one `PALETTES` entry, never a component branch;
- respect `ReviewView.svelte` and `store.svelte.ts` line budgets (only shrink; split logic first);
- preserve the review interaction contracts (4 px click slop, `duration/69` zoom, 50-step history);
- route every screenshot through `KIKUSUB_DEV_SEED` + `--screenshot` or `capture_matrix.sh`, never a visible window.

**Step 4.3 additions (2026-11-25).** The import page is the documented exception to the
1120 px measure: a 760 px "continue current project" card (cover, name, `duration · cues ·
report`, one primary "continue review ⌘3", one quiet "switch film…"). The 40 px drop strip
described here was **removed on 2026-11-26** (see The Import Page Has One Sheet Rule);
the full drop target still only appears when no project is open. The dual-engine review uses the same
`.cue-sheet` primitive as the review table (sheet white, 1 px `--rule`, 7 px radius, 16 px edges).
The sidebar marks the two 原文 pages with paragraph ordinals `①` `②` — a visible mark only; it
never enters the label or the accessible name, because shortcuts, menus and tests match by name.
The settings category list uses the same line icons as the main sidebar (no coloured tiles).

**Step 6 additions (2026-11-26).** Three rulings came out of a real-source run of
`KikuSub-Next.app`:

- **No card shells on workflow pages.** The export page had drifted into
  canvas → big white frame → small white frames (the note bar, the range row, the export
  card, then 3 mode cards + 6 style cards + 4 bitrate cards inside it). The ruling: a
  workflow page is **one ground**; sections are a **title + a 1 px hairline**, never a card;
  an option group keeps **exactly one** interactive layer — transparent with a `--line`
  outline, a hover wash, and a blue outline + `--accent-soft` when selected. Nothing on the
  export page has a background, a border, a radius or a shadow at the section level.
- **The transcribe run bar is docked, not stuck on.** It is the pane's last flex child
  (never `position: sticky` inside the scroller), full-bleed, `color-mix(paper, canvas)`
  with one top hairline, and its content column shares the page's 1120 px / 32 px gutter
  geometry so the recap line sits on the same left edge as the three steps above it. The bar
  itself carries no fill, blur or radius; running shows a 4 px determinate track (neutral
  groove + solid cobalt fill, `aria-valuenow` in step) and the actions collapse to a single
  "stop" danger button.
- **The inspector ends in a footer, not in air.** `.meta-foot` is pinned to the bottom edge
  with `margin-top: auto` and one hairline: status chips on the left, the one "task report"
  link on the right, at most one line of small print. Slack then reads as breathing room
  between content and footer instead of an unfinished panel. The "AI optimisation is off"
  state is a single line (copy + a blue-pencil text link), never a lone white button
  floating in that slack.

**Step 7 additions (2026-11-26).** A second real-source pass on `KikuSub-Next.app` (246 cues,
24 minutes, one pass) produced six visual rulings. What shipped:

- The **light surface hierarchy is inverted**: the page is the paper (`--canvas #FFFFFF`), the chrome
  is one step greyer (`--paper`), the inspector is a third plane (`--bg-inspector`), and everything
  inside a page that used to be a white card is now a **borderless well** (`--well`).
  White is reserved for cue sheets, fields and popovers. *(The exact greys were replaced in Step 8;
  the hierarchy ruling stands, the values did not.)*
- **Dark becomes a stepped carbon console instead of one near-black plane.** *(Step 7 shipped four
  steps and lifting wells; Step 8 replaced both — five neutral steps, sinking wells. The ruling that
  survives is "separate zones by value, do not stripe the screen".)*
- The **appearance button is a two-state switch**; `auto` lives in Settings only.
- The **sidebar ordinals ①② are gone**; the sequencing hint lives in the pages.
- The **朗读 disclosure is one header line** (engine chip + a single "收起") with two even grids
  filling the panel: `1.0× | 上传 | 截取`, then `音色库 | 管理` (pencil, not a second gear).
- **Single-column pages centre** on `--measure-page` (1040 px; import 760 px). Export/import/settings
  no longer leave a slab of empty paper on the right.
- One honest bug found while editing: the compact-mode rules for `.player` / `.table-area` /
  `.transport` had been written in `ReviewView` but **never applied** — Svelte's scoped styles do not
  reach child components. They now live in `ReviewStage` / `ReviewTable` / `ReviewTransport`.

**Step 8 additions (2026-11-26, third real-source pass).** A third run of `KikuSub-Next.app`
produced three defects and three rulings:

- **Dark is now pure neutral carbon with sinking wells** (`#0C0C0E` stage → `#161618` canvas →
  `#1D1D1F` panel → `#242427` surface → `#313135` raise; `#121214` well). The old ladder was
  blue-grey by ~6 levels per step and its wells lifted by 6.5 % white; together that read as a
  grey-teal haze. See *The Nobody's-Teal Rule* and *The Raise Lifts, the Well Sinks Rule*.
- **The blue is Studio royal cobalt** (`#295CE6` / `#2453D4` light, `#3467EB` / `#6B96FF` dark),
  with fill and text as two separate tokens. Text/icon values are one step deeper than fills so an
  11 px glyph clears 4.5:1 on every surface it can land on.
- **The import page holds one sheet** and two hairline-separated sections; the duplicated
  "switch film" bar and its extension pills are gone. See *The Import Page Has One Sheet Rule*.

**Batch 3 additions (2026-11-26).** The six-palette system above shipped with the Settings →
外观与朗读 palette picker (six restrained previews that follow the current light/dark, click to
apply). `verify_phase2_shell.mjs` now measures all 6 × 2 combinations in one renderer process:
body ink, 11 px labels (on paper / well / surface), accent text on paper / canvas / surface,
white primary-button text in normal and hover states, danger / warn / success text, input
border visibility (`--well-line` alpha and contrast), and the luminance direction
(`well < canvas`; dark `raise > surface > canvas`). `tools/shots/verify_ai_toolbar_controls.mjs`
still guards the control edges on the AI pages. Screenshots: `p2-palette-settings-{light,dark}.png`
and `p2-palette-{rose-pine,nord,cinema-amber}-{light,dark}.png` under
`docs/images/refactor-2026-11/`.

**Parallel install and data isolation.** The user's current installed `KikuSub.app` is their daily
driver and must keep working untouched. A redesign build is only ever a *separate* artefact
(`KikuSub-Next.app` and its own bundle id) and only ever writes to its own data root
(`KIKUSUB_DATA_DIR`, `KIKUSUB_PREFERENCES_PATH`, `--user-data-dir`). Never overwrite the installed
app, its `settings.json` / `presets.json`, its Electron `userData`, or `~/.agents/skills/`.
Interface preferences added by this design system belong in `localStorage` (isolated per
`--user-data-dir`), not in a shared config file.
