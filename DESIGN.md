---
name: KikuSub
description: A cue-script interface for a local Japanese subtitle workstation.
colors:
  canvas: "#EDF1F5"
  panel: "#F7F9FB"
  sheet: "#FFFFFF"
  ink: "#15191C"
  ink-2: "#4A545C"
  ink-3: "#566168"
  blue-pencil: "#0B63E5"
  vermilion: "#B8412F"
  approved: "#356B52"
  attention: "#7E5416"
  hairline: "#CCD5DC"
  dark-canvas: "#0B0E11"
  dark-panel: "#12161A"
  dark-sheet: "#171C21"
  dark-ink: "#ECE8DF"
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

### Neutral

- **Canvas** (`#EDF1F5`; dark `#0B0E11`): the desk around the sheet. Lightened one step and
  stripped of the old green-grey cast so the daylight surface reads clean rather than muddy.
- **Panel** (`#F7F9FB`; dark `#12161A`): sidebars, toolbars, inspectors.
- **Sheet** (`#FFFFFF`; dark `#171C21`): the cue table and editable fields — the sheet is now
  pure paper white, so the paper → sheet hierarchy comes from value, not from a grey wash.
- **Sumi** (`#15191C`; dark `#ECE8DF`): primary text, 17.7:1 / 14.0:1.
- **Graphite** (`#4A545C`; dark `#B3B8B8`): secondary text, 7.7:1 / 8.6:1.
- **Slate** (`#566168`; dark `#959FA8`): 11 px labels, counts and units; 6.35:1 / 6.37:1 on the
  sheet. Step 3 darkened this one level so 11 px data no longer sits just above 4.5:1.
- **Hairline** (`#CCD5DC`; dark `#2A3238`): 1 px rules. No 5% grey separators.

### Named Rules

**The One Colour One Job Rule.** Blue means "you can act / this is selected / this is a proposal". Vermilion means "this is a correction or needs attention". Green means "approved / passed". A color never carries a status alone; a word, a mark or an icon travels with it.

**The Dark Is a Room Rule.** Dark is not the light theme inverted. It is the dubbing booth: near-black canvas, paper-warm text, the film still as the brightest plane. Both appearances are audited at 4.5:1 for body text and 3:1 for large text.

### Appearance and the cue face

Appearance is **not** a theme picker. It is one preference with three values — `auto` (follow the
system, the default), `light` (daylight proofing), `dark` (dubbing booth) — plus one orthogonal
preference, the **cue font**: `sans` (Hiragino Sans, default) or `mincho` (Hiragino Mincho).

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

Other pages use a 1120 px measure, left-aligned, with a 320 px right rail for "what happens next". The import page is the exception: a 760 px continue card and a full-width drop target, because the job there is to choose a file, not to read a form.

Spacing follows 4 / 8 / 12 / 16 / 24 / 32. Controls are 24 (inline), 28 (default), 32 (large), 36 (primary). Table rows are 30 px (60 px when bilingual), the cue lane is **17 px** (11 px blocks), the waveform is **80 px** (drag the handle; 72–300 px, remembered per machine). Groups are tight; sections are separated by 1 px hairlines and 16–24 px of air.

The page skeleton is fixed: **titlebar → sidebar → page header → content → status bar**. No page invents its own header height or left edge. The four navigation groups are stages, not eight equal steps.

## Elevation & Depth

Flat by default. Depth is tonal: canvas → panel → sheet. The only shadows are the video frame (a physical screen in a dark room), true popovers/menus, and the selected segment of a segmented control (a native control lift, not a card). Cards do not cast shadows; a card is a sheet with a hairline, not a floating box.

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
- **Ghost:** transparent, graphite text; hover raises to the hover wash.
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

### Cue table

- **Shape:** a cue sheet (`.cue-sheet`: sheet white, 1 px `--rule`, 7 px radius) inset 16 px from the dock; 30 px rows (60 px bilingual); columns `44 px margin | start | end | duration | cue text | row actions`.
- **Cue margin:** 44 px, separated by a 1 px rule. Marks and the cue number both live in it: **approved** = 11 px check (green); **needs review** = 5 px vermilion dot; **machine-written line** = 10 px blue pencil. One mark per row, priority needs-review → approved → pencil.
  - The pencil means "this line already has a translation". It is drawn **only in 原文 mode**: in bilingual or target mode the translation is already on the sheet, so a pencil on every row is a stamp, not information.
  - The active row (selected row, or the block under the playhead) carries a 2 px vermilion line on the margin's left edge and a vermilion number. Hover wash, selected tint, find-hit wash and skipped-hit strike stay as they were.
- **Type:** Japanese 15/20 (13/20 at the minimum window), Chinese 12/16, timecodes **11 mono tabular**, headers 11 px labels (never the cue face, never ink).
- **Rule:** the table is the product; do not hide it behind cards, tabs or a drawer.

### Inspector

- **Shape:** 348 px panel, 42 px tabs, hairline sections; no nested cards.
- **Tabs:** the selected tab is ink + a 2 px blue-pencil rule under it — not a tinted pill. The segmented control (原文 / 译文 / 双语) is the only control that uses the white raised capsule, so the two never read as the same thing. Counts in tabs are tabular numbers, not filled badges.
- **Current cue:** 21/30-scale Japanese field on sheet white with a blue focus ring; 13/19 Chinese; one primary "update this line".
- **A/B:** two aligned rows, full text, one "use B" action below; section CTAs are secondary (paper + hairline). Never a second competing primary.
- **Danger:** delete sits alone at the bottom, after 16 px of air and a hairline.
- **No repeated read-outs:** device, engine, cue count, character count and resolution live in the titlebar and status bar; transcription parameters and version live in the task report. The inspector never restates them.

### Empty states

One icon, one sentence naming the next action, one primary button, one quiet alternative. No illustration, no marketing copy.

## Do's and Don'ts

### Do

- Keep the film still the brightest object on the review screen.
- Put the next action in the page, in the right rail or at the end of the task.
- Use the cue margin for status; use words and marks, not color alone.
- Keep timecodes, durations and counts in tabular mono.
- Test both appearances at 1360×838 and 1080×680.
- Keep the 44 px margin, 30 px rows and 1 px hairlines consistent across pages.
- Let a mark exist only where the fact is invisible elsewhere (that is why the pencil hides in bilingual mode).

### Don't

- Don't nest cards or use a card as a page section.
- Don't use a 5% grey separator or a one-sided border on a rounded box.
- Don't put a primary action in a bottom bar; the status bar is read-only.
- Don't use a display face, gradient text or decorative glass.
- Don't make the interface the hero; the film and the cues are the hero.
- Don't reorder ⌘1–⌘8 without updating the menu bar, the shortcut help and the tests.

## Notes on Implementation

The high-fidelity prototype lives in `.impeccable/prototype/` (workspace root, not shipped). It is static HTML/CSS/JS, rendered through headless Chrome because the real app must not open a window. The production implementation must:
- keep the `html[data-theme]` token mechanism with exactly **two** appearances — light (daylight proofing) and dark (dubbing booth) — resolved from the `auto` / `light` / `dark` preference; mincho is `html[data-cue-font='mincho']`, a cue face on the same palette, never a third colour world;
- respect `ReviewView.svelte` and `store.svelte.ts` line budgets (only shrink; split logic first);
- preserve the review interaction contracts (4 px click slop, `duration/69` zoom, 50-step history);
- route every screenshot through `KIKUSUB_DEV_SEED` + `--screenshot` or `capture_matrix.sh`, never a visible window.

**Parallel install and data isolation.** The user's current installed `KikuSub.app` is their daily
driver and must keep working untouched. A redesign build is only ever a *separate* artefact
(`KikuSub-Next.app` and its own bundle id) and only ever writes to its own data root
(`KIKUSUB_DATA_DIR`, `KIKUSUB_PREFERENCES_PATH`, `--user-data-dir`). Never overwrite the installed
app, its `settings.json` / `presets.json`, its Electron `userData`, or `~/.agents/skills/`.
Interface preferences added by this design system belong in `localStorage` (isolated per
`--user-data-dir`), not in a shared config file.
