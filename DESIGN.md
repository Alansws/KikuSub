---
name: KikuSub
description: A cue-script interface for a local Japanese subtitle workstation.
colors:
  canvas: "#FFFFFF"
  panel: "#F0F2F4"
  inspector: "#F7F8F9"
  sheet: "#FFFFFF"
  well: "#F2F3F4"
  ink: "#15191C"
  ink-2: "#4A545C"
  ink-3: "#566168"
  blue-pencil: "#0B63E5"
  vermilion: "#B8412F"
  approved: "#356B52"
  attention: "#7E5416"
  hairline: "#DBE1E6"
  dark-stage: "#0B0D0F"
  dark-canvas: "#1A1C1F"
  dark-panel: "#24272B"
  dark-inspector: "#1F2226"
  dark-sheet: "#2C3136"
  dark-well: "#2A2D31"
  dark-ink: "#E9E6DF"
  dark-blue-pencil: "#84A9E6"
  dark-vermilion: "#E07A66"
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
    fontFamily: "'Hiragino Sans', 'Hiragino Kaku Gothic ProN', 'Yu Gothic', 'Noto Sans JP', sans-serif"
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
    backgroundColor: "{colors.panel}"
    textColor: "{colors.ink}"
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
    backgroundColor: "rgba(11, 99, 229, 0.09)"
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

A cool paper ground, a sumi ink, and two pencils. The palette is Restrained: one accent does the action, one signal does the correction, one green does approval.

### Primary

- **Blue Pencil** (`#0B63E5`, 5.34:1 on sheet; 5.06:1 on panel; 4.71:1 on canvas): primary actions, current selection, AI proposal marks, links. The 2026-11-25 acceptance pass replaced the old low-chroma steel blue (`#2D5FA6`) with a cleaner cobalt because the old value read grey and muddy on the light surfaces. In dark, `#84A9E6` (7.19:1 on sheet) because a deep blue would disappear. A filled primary button uses `#0B63E5` with white text in light (5.34:1) and the deeper `#2D5FA6` (6.37:1) in dark, where a bright fill would glare.
- **Vermilion** (`#B8412F`, 5.37:1; dark `#E07A66`, 5.84:1): correction, "needs review", the active cue mark, destructive text. Never used for a primary action.

### Neutral (light: the paper desk)

- **Canvas** (`#FFFFFF`): the working stage. In daylight the page itself is **paper white** —
  the desk, not a grey felt under white cards. Every page ground, the cue sheet and the inspector
  live on this value or one step off it.
- **Panel** (`#F0F2F4`): window chrome only — sidebar, titlebar, status bar, timeline dock.
  One neutral step below the paper, so the chrome reads as the frame and the work as the sheet.
- **Inspector** (`#F7F8F9`, `--bg-inspector`): the third plane, half a step between paper and
  chrome. Three adjacent planes (sidebar / work / inspector) are each separable by value alone.
- **Sheet** (`#FFFFFF`): the cue table, fields, popovers. Separated from the paper ground by a
  1 px `--rule`, never by a grey wash.
- **Well** (`rgba(21,25,28,0.05)` → `#F2F3F4` on white, `--well`): the **recessed tonal fill** for
  unselected option blocks, info strips, inputs and grouping rows. No border, no shadow: the block
  is read from value alone. Hover is `--well-hover` (`0.09`), selection adds the blue pencil.
- **Sumi** (`#15191C`; dark `#E9E6DF`): primary text, 15.8:1 / 12.0:1.
- **Graphite** (`#4A545C`; dark `#B6BBB9`): secondary text, 7.7:1 / 8.6:1.
- **Slate** (`#566168`; dark `#98A1A8`): 11 px labels, counts and units; 5.66:1 / 5.71:1 on the
  panel. Step 3 darkened this one level so 11 px data no longer sits just above 4.5:1.
- **Hairline** (`#DBE1E6` rule, `rgba(21,25,28,0.14)` line; dark `#34383D` / `rgba(236,232,223,0.15)`):
  1 px rules. No 5% grey separators.

### Neutral (dark: the carbon console)

Four steps of neutral carbon, borrowed from the grading bay rather than from "black mode". Values
are deliberately **not** near-black: a charcoal room reads professional and lets the film be the
only bright thing on screen.

- **Stage** (`#0B0D0F`, `--stage-bg`): the room around the picture. The darkest value in the app,
  and the only one that is near-black.
- **Canvas** (`#1A1C1F`): the working ground, one step up from the stage.
- **Panel** (`#24272B`): chrome — sidebar, titlebar, status bar, timeline dock.
- **Inspector** (`#1F2226`): the third plane, between canvas and panel.
- **Sheet** (`#2C3136`): the cue table, popovers, fields — the lightest carbon, so a sheet still
  reads as "paper laid on the desk".
- **Well** (`rgba(232,230,224,0.065)` → about `#2A2D31` on canvas): in dark the recessed fill
  **lifts** instead of darkening — same token, opposite direction, because on a dark ground a
  clickable block is a lighter block (this is exactly how Final Cut's controls behave).

### Named Rules

**The One Colour One Job Rule.** Blue means "you can act / this is selected / this is a proposal". Vermilion means "this is a correction or needs attention". Green means "approved / passed". A color never carries a status alone; a word, a mark or an icon travels with it.

**The Dark Is a Room Rule.** Dark is not the light theme inverted. It is the dubbing booth: a
four-step carbon ladder (stage → canvas → inspector → panel → sheet), paper-warm text, the film
still as the brightest plane. Both appearances are audited at 4.5:1 for body text and 3:1 for
large text.

**The No White Frame Rule (2026-11-26).** A white surface may only be a **sheet, a field or a
popover**. Anything that is *a section of a page* — an option group, an info strip, a mode card,
a settings group, an empty state — is either a **title + a hairline** or a **well**. Never a white
card on a grey ground, never a white frame inside a white frame, never a bordered box used as a
section. On the dark side the same rule reads: a card is a carbon step, not a lighter box with a border.

**The Two-State Switch Rule (2026-11-26).** A switch in the chrome answers *"what happens if I
press it"* in one press. The appearance button flips light ⇄ dark directly; `auto` (follow the
system) is a Settings choice, never a third stop in a toolbar cycle. A two-state control that needs
two presses to reach the other state is a three-state control in disguise.

### Appearance and the cue face

Appearance is **not** a theme picker. It is one preference with three values — `auto` (follow the
system, the default), `light` (daylight proofing), `dark` (dubbing booth) — plus one orthogonal
preference, the **cue font**: `sans` (Hiragino Sans, default) or `mincho` (Hiragino Mincho).

The preference lives in **Settings → 外观**; the titlebar button and `⇧⌘A` are a **two-state
switch** (现在 ⇄ 另一面), resolved from what is on screen. So under `auto` + a light system, one
press still lands on dark (it writes the explicit `dark` preference). `auto` is never a stop in
that button's cycle.

- `html[data-theme]` carries only the **resolved** value, `light` or `dark`. There is no third
  colour world; mincho changes `--font-cue` and nothing else.
- Following the system is the HIG-correct default (`dark-mode.md › Best practices`: avoid an
  app-specific appearance setting). The manual override exists because this tool is used at night
  for hours; it lives in Settings, not as a permanent toolbar switch.
- The cue face is a reading preference, not a theme. A user may keep mincho in daylight proofing
  and switch to sans at 2 a.m. without touching the palette.

## Typography

**Display Font:** SF Pro / system sans (with PingFang SC, Hiragino Sans)
**Body Font:** SF Pro / system sans (with PingFang SC)
**Label/Mono Font:** SF Mono (with ui-monospace, Menlo)

**Character:** The voice is the macOS system voice, tuned like a printed cue sheet: tight display tracking, quiet body, Japanese set in Hiragino, and timecodes in tabular mono. No display face, no handwriting font, no type as costume.

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

The import page keeps its own narrower measure (`--measure-card`, **760 px** continue card plus a
40 px drop strip), because the job there is to choose a file, not to read a form — but it is
centred on the same axis.

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
  canvas → inspector → panel → sheet, each one step up. Anything inside a page **lifts** (`--well`,
  lighter than the ground).

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
- **Primary:** blue pencil fill, white text, no border, one per view.
- **Secondary:** panel fill, 1 px hairline, ink text.
- **Soft (tinted secondary, 2026-11-26):** `--well` fill, no border, graphite text, hover
  `--well-hover`. This is the button for a **secondary action that lives on its own** — "去双语翻译"
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

- **Shape:** 5 px radius, `--well` fill, **no border**. Hover `--well-hover`. Selected add a
  1 px `--accent-line` ring plus `--accent-soft`; hover never changes a border.
- **Rule:** one interactive layer. An option group is not a card, and never sits inside another
  outlined box. Explain the option in 13/19 `--ink-2`, never in a second tonal block.
- **Where:** export mode / subtitle style / bitrate presets, engine rows, appearance and cue-font
  previews, prompt templates, settings groups, empty states.

### Cue table

- **Shape:** a cue sheet (`.cue-sheet`: sheet white, 1 px `--rule`, 7 px radius) inset 16 px from the dock; 30 px rows (60 px bilingual); columns `44 px margin | start | end | duration | cue text | row actions`.
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
- keep the `html[data-theme]` token mechanism with exactly **two** appearances — light (daylight proofing) and dark (dubbing booth) — resolved from the `auto` / `light` / `dark` preference; mincho is `html[data-cue-font='mincho']`, a cue face on the same palette, never a third colour world;
- respect `ReviewView.svelte` and `store.svelte.ts` line budgets (only shrink; split logic first);
- preserve the review interaction contracts (4 px click slop, `duration/69` zoom, 50-step history);
- route every screenshot through `KIKUSUB_DEV_SEED` + `--screenshot` or `capture_matrix.sh`, never a visible window.

**Step 4.3 additions (2026-11-25).** The import page is the documented exception to the
1120 px measure: a 760 px "continue current project" card (cover, name, `duration · cues ·
report`, one primary "continue review ⌘3", one quiet "switch film…") above a 40 px drop strip;
the full drop target only appears when no project is open. The dual-engine review uses the same
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
  is one step greyer (`--paper #F0F2F4`), the inspector is a third plane (`--bg-inspector #F7F8F9`),
  and everything inside a page that used to be a white card is now a **borderless well**
  (`--well`, 5 % ink). White is reserved for cue sheets, fields and popovers.
- **Dark is a four-step carbon console** (`#0B0D0F` stage → `#1A1C1F` canvas → `#1F2226` inspector →
  `#24272B` panel → `#2C3136` sheet). Adjacent steps differ by ~10 levels: enough to separate zones,
  not enough to stripe the screen. Wells lift (6.5 % white) instead of sinking.
- The **appearance button is a two-state switch**; `auto` lives in Settings only.
- The **sidebar ordinals ①② are gone**; the sequencing hint lives in the pages.
- The **朗读 disclosure is one header line** (engine chip + a single "收起") with two even grids
  filling the panel: `1.0× | 上传 | 截取`, then `音色库 | 管理` (pencil, not a second gear).
- **Single-column pages centre** on `--measure-page` (1040 px; import 760 px). Export/import/settings
  no longer leave a slab of empty paper on the right.
- One honest bug found while editing: the compact-mode rules for `.player` / `.table-area` /
  `.transport` had been written in `ReviewView` but **never applied** — Svelte's scoped styles do not
  reach child components. They now live in `ReviewStage` / `ReviewTable` / `ReviewTransport`.

**Parallel install and data isolation.** The user's current installed `KikuSub.app` is their daily
driver and must keep working untouched. A redesign build is only ever a *separate* artefact
(`KikuSub-Next.app` and its own bundle id) and only ever writes to its own data root
(`KIKUSUB_DATA_DIR`, `KIKUSUB_PREFERENCES_PATH`, `--user-data-dir`). Never overwrite the installed
app, its `settings.json` / `presets.json`, its Electron `userData`, or `~/.agents/skills/`.
Interface preferences added by this design system belong in `localStorage` (isolated per
`--user-data-dir`), not in a shared config file.
