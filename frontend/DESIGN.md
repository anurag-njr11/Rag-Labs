# RAGLabs — Phase 1 UI design spec

**Figma file:** https://www.figma.com/design/HcaaarGMNWovr8K7fQkEfX
File name: "RAGLabs — Phase 1 UI". Pages: `Screens` (id `0:1`) and `Components` (id `2:4`).

Fetch any node with `get_design_context` using fileKey `HcaaarGMNWovr8K7fQkEfX` and the node id below.

> **Status:** The Figma Starter plan's MCP call limit was reached partway through the build. After that, every Figma MCP call was refused, including writes and screenshots. The frames marked **Drawn** exist in the file. The frames marked **Not drawn** have no Figma node yet. For those, this document's written spec (§6) is the source of truth until they are drawn. All tokens and components they need already exist in the file.

## 1. Frames

| # | Frame name (exact) | Node id | Size | Status |
|---|---|---|---|---|
| 1 | Projects | `9:2` | 1440×900 | Drawn, visually checked |
| 1b | Projects — empty | `9:345` | 1440×900 | Drawn, visually checked |
| 2 | Create — Documents | `12:328` | 1440×900 | Drawn; not visually checked (screenshot blocked by the limit) |
| 2b | Create — Build | `12:610` | 1440×900 | Drawn; not visually checked (screenshot blocked by the limit) |
| 3 | Workspace shell | — | 1440×900 | Not drawn (see §6.1) |
| 3b | Workspace shell — warning | — | 1440×900 | Not drawn (see §6.1) |
| 4 | Documents | — | 1440×900 | Not drawn (see §6.2) |
| 5 | Configure | — | 1440×900 | Not drawn (see §6.3) |
| 6 | Versions | — | 1440×900 | Not drawn (see §6.4) |
| 7 | Playground | — | 1440×900 | Not drawn (see §6.5) |
| 7b | Playground — Trace | — | 1440×900 | Not drawn (see §6.6) |
| 7c | Playground — mobile | — | 390×844 | Not drawn (see §6.7) |
| 8 | API | — | 1440×900 | Not drawn (see §6.8) |

Canvas layout on `Screens`: row y=0 holds the Projects frames (x=0, 1560); row y=1100 holds the Create frames (x=0, 1560).

### Components (page `Components`, id `2:4`)

| Component | Node id | Type |
|---|---|---|
| Icons (42 Lucide icons, `Icon/<name>`, 16px) | frame `3:2` | components |
| Badge | `4:74` | component set |
| Button | `4:123` | component set |
| Tab | `4:136` | component set |
| Chip | `4:156` | component set |
| Stepper step | `4:173` | component set |
| Progress bar | `4:186` | component set |
| Switch | `4:193` | component set |
| Input | `4:208` | component set |
| Select | `4:219` | component set |
| Field/Slider (Slider row) | `7:57` | component |
| Field/Toggle (Toggle row) | `7:74` | component |
| Field/Select | `7:92` | component |
| Card/Option (type picker) | `7:163` | component set |
| Card/Project | `7:209` | component |
| Table row/Document | `7:259` | component |

Icon ids: bolt `3:5`, refresh `3:11`, check `3:14`, x `3:18`, alert `3:23`, file `3:30`, upload `3:35`, link `3:39`, search `3:43`, chevron-down `3:46`, chevron-right `3:49`, copy `3:53`, send `3:57`, database `3:62`, trash `3:67`, more `3:72`, plus `3:76`, clock `3:80`, loader `3:83`, target `3:88`, approx `3:92`, dense `3:99`, keyword `3:104`, code `3:108`, globe `3:113`, info `3:118`, layers `3:123`, rollback `3:127`, commit `3:132`, play `3:135`, sliders `3:146`, key `3:151`, table `3:157`, lock `3:161`, circle `3:164`, check-circle `3:168`, x-circle `3:173`, terminal `3:177`, message `3:180`, eye `3:184`, folder `3:187`, cpu `3:199`. In code, use `lucide-react` with the same names (`Zap`, `RefreshCw`, `Check`, `X`, `TriangleAlert`, `FileText`, `Upload`, `Link`, `Search`, `ChevronDown`, `ChevronRight`, `Copy`, `ArrowUp`, `Database`, `Trash`, `Ellipsis`, `Plus`, `Clock`, `LoaderCircle`, `Target`, `Waves`-style approx, `Code`, `Type`, `Globe`, `Info`, `Layers`, `RotateCcw`, `GitCommitHorizontal`, `Play`, `SlidersHorizontal`, `KeyRound`, `Table`, `Lock`, `Circle`, `CircleCheck`, `CircleX`, `Terminal`, `MessageCircle`, `Eye`, `Folder`, `Cpu`). The Figma icon `dense` is a custom "scatter + vector" glyph; `Spline` or `Waypoints` is a fine substitute.

## 2. Design tokens

Figma variables: collections `Color` (mode Light; 48 vars), `Spacing` (13), `Radius` (6). The Starter plan allows one variable mode, so the **dark values live only in this spec**. Every Figma variable's WEB code syntax is `var(--color-<group>-<name>)` / `var(--radius-<name>)`.

Font: **Inter** (UI) and **JetBrains Mono** (numbers, code, IDs, file sizes, scores). Both are on Google Fonts.

### 2.1 Colors

| Token | Light | Dark | Use |
|---|---|---|---|
| bg-canvas | #F7F7F8 | #0B0B0D | App background |
| bg-surface | #FFFFFF | #141417 | Cards, bars, panels |
| bg-subtle | #F4F4F5 | #1B1B1F | Wells, table headers, dropzone |
| bg-muted | #E9E9EC | #26262B | Tracks, segment containers |
| bg-inverse | #18181B | #FAFAFA | Logo mark, tooltips |
| bg-code | #111114 | #0F0F12 | Code blocks and logs (dark in both themes) |
| border-default | #E4E4E7 | #2A2A30 | Hairlines, card borders |
| border-strong | #D4D4D8 | #3A3A42 | Inputs, secondary buttons |
| border-focus | #6366F1 | #818CF8 | Focus ring |
| text-primary | #18181B | #FAFAFA | Body and headings |
| text-secondary | #52525B | #A1A1AA | Help text, meta |
| text-tertiary | #71717A | #8B8B94 | Captions, placeholders |
| text-disabled | #A1A1AA | #52525B | Disabled |
| text-inverse | #FFFFFF | #18181B | On accent/inverse |
| text-code | #E4E4E7 | #E4E4E7 | Text on bg-code |
| accent-default | #4F46E5 | #818CF8 | Primary actions, selection |
| accent-hover | #4338CA | #A5B4FC | Primary hover |
| accent-subtle | #EEF2FF | #1E1B4B | Selected backgrounds, citation chips |
| accent-border | #C7D2FE | #3730A3 | Citation chip border |
| accent-text | #4338CA | #A5B4FC | Accent text on subtle |
| instant-fg / bg / border | #0369A1 / #E0F2FE / #BAE6FD | #7DD3FC / #0C2A3D / #164E63 | ⚡ Instant effect |
| rebuild-fg / bg / border | #C2410C / #FFEDD5 / #FED7AA | #FDBA74 / #3B1D0A / #7C2D12 | 🔁 Rebuild effect |
| success-fg / bg / border | #15803D / #DCFCE7 / #BBF7D0 | #4ADE80 / #0F2E1B / #14532D | Ready, Indexed, Good, Exact store |
| warning-fg / bg / border | #A16207 / #FEF9C3 / #FDE68A | #FACC15 / #332A07 / #713F12 | Fair, warnings, missing key banner |
| danger-fg / bg / border | #B91C1C / #FEE2E2 / #FECACA | #F87171 / #3B1212 / #7F1D1D | Failed, Poor, delete |
| info-fg / bg / border | #1D4ED8 / #DBEAFE / #BFDBFE | #93C5FD / #172554 / #1E3A8A | Building, running |
| neutral-fg / bg / border | #52525B / #F4F4F5 / #E4E4E7 | #A1A1AA / #1F1F23 / #34343A | Pending, No documents, approximate |
| dense-fg / bg | #6D28D9 / #EDE9FE | #C4B5FD / #2E1F5E | Found by dense |
| keyword-fg / bg | #0F766E / #CCFBF1 | #5EEAD4 / #0B302C | Found by keyword (BM25) |
| exact-fg / bg | #BE185D / #FCE7F3 | #F9A8D4 / #3D1028 | Found by exact match |
| highlight-bg | #FEF08A | #4D3F06 | Cited sentence highlight |

All `*-fg` values on their `*-bg` pass WCAG AA for 11–13px text (≥ 4.5:1) in light mode.

### 2.2 Type scale (Figma text styles `text/*`)

| Token | Font | Size / line-height | Weight | Tracking |
|---|---|---|---|---|
| display | Inter | 24 / 32 | 600 | -0.4px |
| title | Inter | 18 / 26 | 600 | -0.2px |
| heading | Inter | 14 / 20 | 600 | 0 |
| label | Inter | 13 / 18 | 500 | 0 |
| body | Inter | 13 / 20 | 400 | 0 |
| body-sm | Inter | 12 / 16 | 400 | 0 |
| caption | Inter | 11 / 14 | 500 | 0.1px |
| mono | JetBrains Mono | 12 / 18 | 400 | 0 |
| mono-sm | JetBrains Mono | 11 / 14 | 500 | 0 |

The base UI size is 13px, which keeps the layout dense and in line with Linear/Vercel.

### 2.3 Spacing, radius, shadow

- **Spacing** (px): 0, 2, 4, 6, 8, 12, 16, 20, 24, 32, 40, 48, 64. Tailwind v4's default `--spacing: 0.25rem` covers these (px ÷ 4 → `p-1`, `p-2`, `p-3`, `p-4`, `p-5`, `p-6`, `p-8`, `p-10`, `p-12`, `p-16`; `p-0.5` = 2px, `p-1.5` = 6px). *Note:* the Figma spacing variables carry the code syntax `var(--spacing-N)` where N = px. In code, use the Tailwind step (px ÷ 4), not N.
- **Radius:** none 0, sm 4 (badges, citation chips), md 6 (buttons, inputs), lg 8 (cards, tables), xl 12 (empty states, modals), full 999 (pills, switches, avatars).
- **Shadows** (Figma effect styles `shadow/*`): sm `0 1px 2px rgb(16 16 19 / .05)`; md `0 1px 3px rgb(16 16 19 / .06), 0 4px 12px rgb(16 16 19 / .06)`; lg `0 4px 8px rgb(16 16 19 / .06), 0 12px 32px rgb(16 16 19 / .12)`. In dark mode, rely on borders and use black at 3× the alpha.
- **Focus ring:** 1px `border-focus` border plus a 3px ring at `rgb(79 70 229 / .18)`.

### 2.4 Tailwind v4 `@theme` (paste into `src/index.css`)

```css
@import "tailwindcss";

@custom-variant dark (&:where(.dark, .dark *));

@theme {
  /* Fonts */
  --font-sans: "Inter", ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
  --font-mono: "JetBrains Mono", ui-monospace, "SFMono-Regular", Menlo, Consolas, monospace;

  /* Type scale */
  --text-display: 24px;  --text-display--line-height: 32px; --text-display--font-weight: 600; --text-display--letter-spacing: -0.4px;
  --text-title: 18px;    --text-title--line-height: 26px;   --text-title--font-weight: 600;   --text-title--letter-spacing: -0.2px;
  --text-heading: 14px;  --text-heading--line-height: 20px; --text-heading--font-weight: 600;
  --text-label: 13px;    --text-label--line-height: 18px;   --text-label--font-weight: 500;
  --text-body: 13px;     --text-body--line-height: 20px;
  --text-body-sm: 12px;  --text-body-sm--line-height: 16px;
  --text-caption: 11px;  --text-caption--line-height: 14px; --text-caption--font-weight: 500; --text-caption--letter-spacing: 0.1px;
  --text-mono: 12px;     --text-mono--line-height: 18px;
  --text-mono-sm: 11px;  --text-mono-sm--line-height: 14px; --text-mono-sm--font-weight: 500;

  /* Radius */
  --radius-none: 0px; --radius-sm: 4px; --radius-md: 6px; --radius-lg: 8px; --radius-xl: 12px; --radius-full: 9999px;

  /* Shadows */
  --shadow-sm: 0 1px 2px rgb(16 16 19 / 0.05);
  --shadow-md: 0 1px 3px rgb(16 16 19 / 0.06), 0 4px 12px rgb(16 16 19 / 0.06);
  --shadow-lg: 0 4px 8px rgb(16 16 19 / 0.06), 0 12px 32px rgb(16 16 19 / 0.12);
  --shadow-focus: 0 0 0 3px rgb(79 70 229 / 0.18);

  /* Colors — light (default) */
  --color-bg-canvas: #F7F7F8;  --color-bg-surface: #FFFFFF; --color-bg-subtle: #F4F4F5;
  --color-bg-muted: #E9E9EC;   --color-bg-inverse: #18181B; --color-bg-code: #111114;
  --color-border-default: #E4E4E7; --color-border-strong: #D4D4D8; --color-border-focus: #6366F1;
  --color-text-primary: #18181B; --color-text-secondary: #52525B; --color-text-tertiary: #71717A;
  --color-text-disabled: #A1A1AA; --color-text-inverse: #FFFFFF; --color-text-code: #E4E4E7;
  --color-accent-default: #4F46E5; --color-accent-hover: #4338CA; --color-accent-subtle: #EEF2FF;
  --color-accent-border: #C7D2FE;  --color-accent-text: #4338CA;
  --color-instant-fg: #0369A1; --color-instant-bg: #E0F2FE; --color-instant-border: #BAE6FD;
  --color-rebuild-fg: #C2410C; --color-rebuild-bg: #FFEDD5; --color-rebuild-border: #FED7AA;
  --color-success-fg: #15803D; --color-success-bg: #DCFCE7; --color-success-border: #BBF7D0;
  --color-warning-fg: #A16207; --color-warning-bg: #FEF9C3; --color-warning-border: #FDE68A;
  --color-danger-fg: #B91C1C;  --color-danger-bg: #FEE2E2;  --color-danger-border: #FECACA;
  --color-info-fg: #1D4ED8;    --color-info-bg: #DBEAFE;    --color-info-border: #BFDBFE;
  --color-neutral-fg: #52525B; --color-neutral-bg: #F4F4F5; --color-neutral-border: #E4E4E7;
  --color-dense-fg: #6D28D9;   --color-dense-bg: #EDE9FE;
  --color-keyword-fg: #0F766E; --color-keyword-bg: #CCFBF1;
  --color-exact-fg: #BE185D;   --color-exact-bg: #FCE7F3;
  --color-highlight-bg: #FEF08A;
}

/* Dark theme: toggle with <html class="dark">. Utilities read the variables, so overriding them is enough. */
.dark {
  --color-bg-canvas: #0B0B0D;  --color-bg-surface: #141417; --color-bg-subtle: #1B1B1F;
  --color-bg-muted: #26262B;   --color-bg-inverse: #FAFAFA; --color-bg-code: #0F0F12;
  --color-border-default: #2A2A30; --color-border-strong: #3A3A42; --color-border-focus: #818CF8;
  --color-text-primary: #FAFAFA; --color-text-secondary: #A1A1AA; --color-text-tertiary: #8B8B94;
  --color-text-disabled: #52525B; --color-text-inverse: #18181B; --color-text-code: #E4E4E7;
  --color-accent-default: #818CF8; --color-accent-hover: #A5B4FC; --color-accent-subtle: #1E1B4B;
  --color-accent-border: #3730A3;  --color-accent-text: #A5B4FC;
  --color-instant-fg: #7DD3FC; --color-instant-bg: #0C2A3D; --color-instant-border: #164E63;
  --color-rebuild-fg: #FDBA74; --color-rebuild-bg: #3B1D0A; --color-rebuild-border: #7C2D12;
  --color-success-fg: #4ADE80; --color-success-bg: #0F2E1B; --color-success-border: #14532D;
  --color-warning-fg: #FACC15; --color-warning-bg: #332A07; --color-warning-border: #713F12;
  --color-danger-fg: #F87171;  --color-danger-bg: #3B1212;  --color-danger-border: #7F1D1D;
  --color-info-fg: #93C5FD;    --color-info-bg: #172554;    --color-info-border: #1E3A8A;
  --color-neutral-fg: #A1A1AA; --color-neutral-bg: #1F1F23; --color-neutral-border: #34343A;
  --color-dense-fg: #C4B5FD;   --color-dense-bg: #2E1F5E;
  --color-keyword-fg: #5EEAD4; --color-keyword-bg: #0B302C;
  --color-exact-fg: #F9A8D4;   --color-exact-bg: #3D1028;
  --color-highlight-bg: #4D3F06;
  --shadow-sm: 0 1px 2px rgb(0 0 0 / 0.15);
  --shadow-md: 0 1px 3px rgb(0 0 0 / 0.2), 0 4px 12px rgb(0 0 0 / 0.2);
  --shadow-lg: 0 4px 8px rgb(0 0 0 / 0.2), 0 12px 32px rgb(0 0 0 / 0.36);
}

@layer base {
  html { font-family: var(--font-sans); font-size: 13px; }
  body { @apply bg-bg-canvas text-text-primary text-body antialiased; }
  code, kbd, pre, .tabular { font-variant-numeric: tabular-nums; }
}
```

Load the fonts in `index.html`:
`<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">`

Class examples: `bg-bg-surface border border-border-default rounded-lg shadow-sm`, `text-label text-text-secondary`, `bg-rebuild-bg text-rebuild-fg`.

## 3. Component inventory

| Component | Variants / states | Properties | Usage |
|---|---|---|---|
| **Button** | Variant: Primary · Secondary · Ghost · Danger × Size: md (32px) · sm (24px). States in code: hover (Primary → accent-hover; others → bg-subtle), focus (focus ring), disabled (opacity .45) | Label, Show icon, Icon (swap) | One Primary per view. Ghost for toolbars and row actions. Danger for destructive actions. Icon-only = Ghost sm with the label hidden (add an `aria-label`). |
| **Badge** | Tone: Neutral, Accent, Success, Info, Warning, Danger, Instant, Rebuild, Dense, Keyword, Exact, StoreExact, StoreApprox | Label, Show lead | 18px tall, radius sm, caption text. Status tones lead with a 6px dot; meaning tones lead with a 12px icon (see §4). |
| **Tab** | Style: Underline · Segment × State: Active · Inactive | Label | Underline is for workspace tabs (active = 2px text-primary underline). Segment is for panel sub-tabs and filters, inside a `bg-muted p-0.5 rounded-lg` track. |
| **Input** | State: Default · Focus (+ disabled/error in code: error = danger-fg border + help text in danger-fg) | Value, Show icon, Icon, Show suffix, Suffix | 32px, radius md, border-strong. Placeholder uses text-tertiary. Numbers/URLs use mono. |
| **Select** | State: Default · Disabled | Value | Same metrics as Input, with a trailing chevron. Used for enums and model pickers. |
| **Switch** | On: true · false | — | 28×16. Always paired with a label (Toggle row). |
| **Field/Slider** (Slider row) | — | Label, Value, Unit, Min, Max, Help | Label + ⚡/🔁 badge, numeric input (72px, mono) with unit, 4px slider track, min/max labels, help. |
| **Field/Toggle** (Toggle row) | — | Label, Help | Label + effect badge + help on the left, Switch on the right. |
| **Field/Select** | — | Label, Help | Label + effect badge, full-width Select, help. |
| **Card** (base surface) | default · interactive (hover border-strong + shadow-md) · selected (accent border 1.5px + accent-subtle) | — | `bg-surface border-default rounded-lg shadow-sm p-4/5`. All panels use it. |
| **Card/Project** | Status badge: Ready / Building / Failed / No documents | Name, Description, Docs, Chunks, Store, Model, Updated | Grid card; the whole card is a link. The description clamps to 1–2 lines. |
| **Card/Option** (type picker) | State: Default · Selected · Disabled | Title, Description, Reason; nested Badge 1/2 | Radio card. Disabled shows a lock + reason ("Add NVIDIA_API_KEY to .env") and is not focusable for selection, but can show a tooltip. |
| **Table row/Document** | Status Indexed/Failed/Pending × Parse Good/Fair/Poor | Ext, Filename, Type, Size, Chunks | 52px row, bottom hairline, hover bg-subtle. Columns: file (fill) · type 80 · size 80 · status 100 · chunks 72 · parse 100 · actions 132. |
| **Progress bar** | Tone: Accent (running) · Success · Danger · Neutral (queued) | — | 6px, radius full, track bg-muted. |
| **Stepper step** | State: Done · Current · Upcoming | Label, Number | Steps joined by 48×1 connectors (accent when completed). |
| **Chip** | Kind: Citation · Source · Pill | Label | Citation `[n]`: 18px mono chip, accent-subtle, links to Sources item n. Source: "models.md · p.4" with a file icon. Pill: header metadata (version, index status). |

## 4. Semantic mappings (color + icon)

The same meaning always uses the same color and the same icon. Never rely on color alone: each badge has an icon or a text label.

| Concept | Value | Tone tokens | Icon (Lucide) | Label text |
|---|---|---|---|---|
| Parameter effect | ⚡ Instant | instant-* (sky) | `Zap` | "Instant" — applies at query time, no re-index |
| | 🔁 Rebuild | rebuild-* (orange) | `RefreshCw` | "Rebuild" — requires re-indexing |
| Vector store search | Exact | success-* | `Target` | "Exact" — deterministic (Flat / brute force) |
| | Approximate | neutral-* | approx waves (`Waves`) | "Approximate" — HNSW / IVF |
| Found-by path | dense | dense-* (violet) | scatter/vector (`Waypoints`) | "dense" — vector similarity |
| | keyword | keyword-* (teal) | `Type` | "keyword" — BM25 |
| | exact | exact-* (pink) | `Code` | "exact" — exact error message / code symbol match |
| Build / doc status | Ready / Indexed | success-* | dot (`CircleCheck` in rows) | "Ready", "Indexed" |
| | Building / running | info-* | dot (`LoaderCircle`, spinning, in rows) | "Building" |
| | Failed | danger-* | dot (`CircleX` in rows) | "Failed" |
| | Pending / queued / No documents | neutral-* | dot (`Circle` in rows) | "Pending", "No documents" |
| Parse quality | Good | success-* | dot | "Good" |
| | Fair | warning-* | dot | "Fair" |
| | Poor | danger-* | dot | "Poor" |
| Chunk state (Inspector) | In context | accent-* | dot | "In context" |
| | Cited | success-* | `Check` | "Cited" |
| | Dropped for budget | neutral-* (strike score) | dot | "Dropped for budget" |

Score chips in the Inspector use the path colors: `dense 0.82` (dense-*), `keyword 7.1` (keyword-*), `exact 2.0` (exact-*), `fused 0.049` (neutral), `rerank 5.2` (accent). They use mono-sm on a `*-bg` fill.

## 5. Layout system

- **Desktop frame:** 1440×900. The top bar is 52px (logo mark 24px `bg-inverse` rounded-md + "RAGLabs" heading + "Phase 1" neutral badge; right side: Ghost "Docs", 28px avatar).
- **Page gutters:** 48px (Projects), 32px (workspace). Content max width is 1344px (Projects grid), or full width minus gutters in the workspace.
- **Projects grid:** 4 columns at 1440 (`grid-cols-4 gap-4`, card ≈ 324px wide); 3 below 1280px, 2 below 1024px, 1 below 640px.
- **Wizard:** centered 880px column. The stepper sits in a white header band. A sticky footer (white, top hairline) holds "Step n of 4" or a hint on the left and actions on the right.
- **Workspace:** top bar → project header (breadcrumb, name, pills, tabs; white, bottom hairline) → tab content on bg-canvas.
- **Sticky bars:** the wizard footer and the Configure change bar are `position: sticky; bottom: 0` with bg-surface, a top hairline and shadow-md facing up. Content scrolls under them; add bottom padding equal to the bar height.
- **Configure:** a 240px sticky stage nav (top offset = header height) plus a main column of max 880px, with a 32px gap.
- **Playground (desktop):** two panes that fill the viewport height under the workspace header. Chat is ≈60% (`flex-[3]`, min 560px); the Inspector is ≈40% (`flex-[2]`, min 420px), separated by a 1px border-default; each pane scrolls independently. The chat input is pinned to the bottom of the chat pane. Clicking a citation chip `[n]` scrolls the Inspector to item n and flashes it (accent-subtle, 600ms).
- **Playground (mobile ≤ 768px):** one column. The chat comes first. The Inspector collapses into a bottom section (Sources | Trace segment tabs), collapsed by default to a 48px summary bar ("8 sources · 3 cited · 1.9s"); tap it to expand inline under the latest answer or as a bottom sheet (max 70vh). The input stays pinned at the bottom (safe-area aware). Citation taps open the sheet at that source. The workspace tabs scroll horizontally.
- **Tables:** a 36px header row on bg-subtle with caption uppercase-free labels in text-tertiary, 52px body rows, numeric columns right-aligned in mono.

## 6. Written spec for the frames that are not drawn yet

Build these from the components and tokens above. The content uses the Pydantic docs corpus.

### 6.1 Workspace shell (+ "Workspace shell — warning")
- **Header** (bg-surface, padding 16/32/0, bottom hairline):
  - Breadcrumb: `Projects` (tertiary link) › `Pydantic docs` (secondary), body-sm.
  - Title row: "Pydantic docs" in display, then the Pill chips "v3 · active" (commit icon) and "Index ready · 1,240 chunks · FAISS" (database icon, success dot). Right side: Secondary "Rebuild index" (refresh icon) and Ghost icon button (more).
  - Underline tabs, 20px apart: Documents · Configure · Versions · Playground · API.
- **Warning variant:** a full-width banner between the top bar and the header: warning-bg fill, bottom border warning-border, alert icon in warning-fg, label "No LLM API key configured —" followed by body "add `GEMINI_API_KEY` or `NVIDIA_API_KEY` to `.env`" (keys in mono), plus a Ghost sm "How to" button on the right. Height 40px.

### 6.2 Documents tab
- Header row: "42 documents · 1,240 chunks · 6.8 MB" (label) with a search Input (240px). Right side: Secondary "Add URL" (link) and Primary "Upload files" (upload).
- Table (Card, radius lg, clip): header row, then `Table row/Document` rows:
  - `models.md` · Markdown · 48 KB · Indexed · 112 · Good
  - `fields.md` · Markdown · 36 KB · Indexed · 94 · Good
  - `errors/validation_errors.md` · Markdown · 61 KB · Indexed · 171 · Good
  - `concepts/json_schema.md` · Markdown · 22 KB · Indexed · 58 · Good
  - `pydantic-v2-migration.pdf` · PDF · 1.4 MB · Indexed · 206 · **Fair**
  - `api/config.html` · HTML · 88 KB · Pending · — · —
  - `scanned-cheatsheet.pdf` · PDF · 3.1 MB · **Failed** · 0 · **Poor**
- **Parse-quality hover card** (anchored to the "Fair" badge; 300px, bg-surface, shadow-lg, radius lg, padding 12):
  - Title "Parse quality: Fair" (warning dot), then warnings with alert icons: "3 pages have little or no text (p. 12, 13, 27)" and "2 tables detected with merged cells".
  - Stats grid (caption label / mono value): Pages 34 · Tables found 6 · Header lines removed 68 · Chunks 206.
  - Footer link: "View parsed text →".
- Row actions: Ghost sm "Re-index" and a Ghost icon (trash) for delete; a confirm popover says "Delete fields.md and its 94 chunks? Takes effect on next build."

### 6.3 Configure tab (core)
- **Left: sticky stage nav**, 240px. A list of 8 items, each 44px: step number (mono-sm tertiary), stage name (label), and the chosen type under it (body-sm tertiary). Active item: bg-surface, border-default, 2px accent left bar. Items that have unsaved changes show a 6px rebuild/instant dot.
  - 1 Parse — Auto (Docling-lite)
  - 2 Chunk — Recursive
  - 3 Embed — text-embedding-004
  - 4 Vector store — FAISS
  - 5 Retrieve — Hybrid (dense + BM25 + exact)
  - 6 Rerank — Cross-encoder
  - 7 Prompt — Cited answer
  - 8 Generate — gemini-2.5-flash
- **Main: one Card per stage** (gap 16):
  - Header: "2 · Chunk" (title) plus a one-line description ("Split parsed documents into retrievable passages.").
  - Type picker: a grid of `Card/Option`, 3 per row.
  - Parameter fields: 2-column grid of Field rows, 24px gap.
  - An "Advanced" disclosure row (chevron + label + "3 more"), bottom-bordered.
- **Examples per stage:**
  - Chunk: options Fixed · **Recursive** (selected) · Markdown-aware · Semantic. Fields: Field/Slider "Chunk size" 1000 chars 🔁; Field/Slider "Overlap" 150 chars 🔁; Field/Select "Unit" chars/tokens 🔁; Field/Toggle "Strip headers & footers" 🔁 (on).
  - Vector store: options NumPy [Exact, Local] · **FAISS** [Exact / Approximate, Local] · Chroma [Approximate, Local] · Qdrant [Approximate, Server] · LanceDB [Approximate, Local]. Fields: Select "Index type" Flat / HNSW / IVF 🔁. Advanced opened: Slider "HNSW efSearch" 64 ⚡, "HNSW M" 32 🔁.
  - Retrieve: Slider "top_k" 8 ⚡; toggles "Dense" / "Keyword (BM25)" / "Exact match" ⚡, each with its path badge; Select "Fusion" RRF ⚡.
  - Rerank: options None · **Cross-encoder** · NVIDIA rerank (**disabled**, reason "Add NVIDIA_API_KEY to .env"); Slider "Keep top n" 5 ⚡.
  - Prompt: a text area (6 rows, mono) "Custom system prompt" ⚡, prefilled "You are a precise assistant for the Pydantic docs. Answer only from the sources and cite them as [n]…"; Slider "Context budget" 6,000 tokens ⚡.
  - Generate: Field/Select "Model" (gemini-2.5-flash · gemini-2.5-pro · llama-3.3-70b (NVIDIA, disabled)) ⚡; Slider "Temperature" 0.2 ⚡.
- **Sticky bottom bar** (bg-surface, top hairline, shadow-md, 64px):
  - Left: "3 changes · 2 need rebuild" (label) plus Rebuild ×2 / Instant ×1 badges, and body-sm tertiary "Vectors cached — re-inserts 1,240 chunks, no re-embedding".
  - Middle: Input (fill, max 320px) with placeholder "Note for this version (optional)".
  - Right: Secondary "Reset to recommended" and Primary "Save as v4".

### 6.4 Versions tab
- **Left list** (320px Card, rows 64px): v4 "Smaller chunks for API reference" · just now · `idx 9f3c2a` · Building (Info) · — ; **v3** "Hybrid + rerank" · 2h ago · `idx 71be04` · Ready · **active** (Accent badge) ; v2 "Switch to FAISS" · yesterday · `idx 71be04` · Ready ; v1 "Initial" · 3d ago · `idx 0a19d7` · Ready. The selected row gets bg-accent-subtle and a 2px left accent bar.
- **Right detail Card:**
  - Header: "v4" title, note, meta "Created by you · Sep 23, 12:10 · index hash `9f3c2a`". Actions: Primary "Make active" (the Figma frame still shows a "Roll back to this" button — removed in code, activation covers it).
  - "Changes vs v3" diff table: mono rows `Stage · param`, `old → new` (old struck through in text-tertiary, new in text-primary), effect badge:
    - Chunk · size: 1000 → 800 [🔁 Rebuild]
    - Chunk · overlap: 150 → 120 [🔁 Rebuild]
    - Retrieve · top_k: 8 → 5 [⚡ Instant]
    - Prompt · system_prompt: edited (+2 lines) [⚡ Instant]
  - Summary footer: "2 rebuild changes — activating v4 re-chunks and re-embeds 1,240 chunks (~1 min)."

### 6.5 Playground (Sources)
- **Chat pane (≈60%):**
  - Toolbar: Select "v3 · active" (140px), Ghost "New chat", and meta on the right "gemini-2.5-flash · FAISS".
  - User bubble (bg-surface, border, right-aligned, max 560px): "How do I make a field optional with a default?"
  - Assistant answer, no bubble, with body text. The citation chips are inline in the text:
    > "In Pydantic v2 a field is optional only when it has a default. Annotate it as `int | None` and give it a default, e.g. `age: int | None = None` [1]. Using `Optional[int]` without a default makes the field *required* but nullable [2]. For mutable defaults use `Field(default_factory=list)` [1]."
  - The streaming state is a blinking 2px caret at the end, plus a "Generating…" caption with a spinner.
  - Source chips row: `models.md · p.4`, `fields.md · p.2`.
  - Actions: copy, thumbs, "Show trace".
  - Input (bottom, 3-line textarea, radius lg, shadow-sm) with the send button (Primary sm icon, arrow-up). Hint: "Enter to send · Shift+Enter for newline · answers cite sources as [n]".
- **Inspector (≈40%):** header "Inspector", Segment tabs **Sources** | Trace, and the summary "8 retrieved · 5 in context · 2 cited".
- **Source item** (Card, padding 12, gap 8):
  - Row 1: rank "#1" (mono, 24px square, bg-subtle), `models.md`, "p.4", and the state badges Cited (success) + In context (accent).
  - Row 2: heading path in body-sm tertiary: "Models › Fields › Optional fields".
  - Row 3: found-by badges dense · keyword, then score chips `dense 0.82` `keyword 7.1` `fused 0.049` `rerank 5.2`.
  - Row 4: chunk text (body, 4-line clamp, "Show more"), with the cited sentence highlighted (highlight-bg, radius 2).
  - Items:
    - #2 `fields.md` p.2 "Fields › Required vs optional" — dense+exact, `exact 2.0`, Cited.
    - #3 `errors/validation_errors.md` "Errors › missing" — keyword+exact, In context.
    - #6 `pydantic-v2-migration.pdf` p.11 — dense, **Dropped for budget** (neutral, 60% opacity).
  - **Table-chunk variant:** #4 `concepts/json_schema.md` "JSON Schema › Field types" renders the chunk as a compact table (3 columns "Python type / JSON Schema / Notes", 4 rows, mono cells, 1px borders) instead of prose. Badge: "Table".

### 6.6 Playground — Trace
Same chat pane; the Inspector's Trace tab is active.
- Store badge row: "FAISS · Flat · exact" (StoreExact) plus "trace id `tr_8c1f…`" (copy).
- Table columns: Step (mono) · ms (right, mono) with an inline bar (max 160px; the bar is proportional to the slowest step, accent at 30% opacity, the generate bar full accent) · Tokens in/out · Cost.

| step | ms | tokens in / out | cost |
|---|---|---|---|
| embed_query | 42 | 14 / — | $0.00000 |
| dense_search | 3 | — | — |
| keyword_search | 5 | — | — |
| exact_search | 1 | — | — |
| fuse | 1 | — | — |
| rerank | 118 | 3,420 / — | $0.00017 |
| prompt | 2 | — | — |
| generate | 1,612 | 4,905 / 212 | $0.00043 |
| **Total** | **1,784** | **8,339 / 212** | **$0.00060** |

- The totals row is bold on bg-subtle. Below it, a collapsible "Prompt sent to model" code block (bg-code, mono) shows the assembled prompt.

### 6.7 Playground — mobile (390×844)
- Top: a compact bar (logo, "Pydantic docs", version Select sm), then horizontally scrollable underline tabs with Playground active.
- The chat thread is full width with the same message content; the citation chips stay inline.
- Under the answer, a collapsed Inspector summary card: "Sources 8 · Trace 1.8 s ›", with Segment tabs inside once expanded. Show it expanded as a bottom sheet with the drag handle, Sources tab, and the first 2 source items.
- The input is pinned at the bottom with a 44px send button.

### 6.8 API tab
- Card "Query endpoint": method badge `POST` (Accent) plus the URL `http://localhost:8000/api/projects/pydantic-docs/query` (mono, with a copy button). Beneath it, "Uses the active version (v3) unless `version` is given."
- Code block "curl" (bg-code, mono, copy button top-right):
  ```bash
  curl -X POST http://localhost:8000/api/projects/pydantic-docs/query \
    -H "Content-Type: application/json" \
    -d '{"question": "How do I make a field optional with a default?", "version": 3, "top_k": 5}'
  ```
- Code block "Response":
  ```json
  {
    "answer": "Annotate it as `int | None` and give it a default, e.g. `age: int | None = None` [1]…",
    "citations": [
      {"n": 1, "document": "models.md", "page": 4, "chunk_id": "c_0412", "heading_path": ["Models", "Fields", "Optional fields"]},
      {"n": 2, "document": "fields.md", "page": 2, "chunk_id": "c_0133", "heading_path": ["Fields", "Required vs optional"]}
    ],
    "version": 3,
    "timings_ms": {"retrieve": 10, "rerank": 118, "generate": 1612, "total": 1784},
    "usage": {"input_tokens": 8339, "output_tokens": 212, "cost_usd": 0.0006}
  }
  ```
- A short explanation list: "Answers are generated with the active version's pipeline", "`citations[n]` matches the `[n]` markers in `answer`", "Set `stream: true` for Server-Sent Events", "Requires the server's `.env` LLM key; no client key needed in Phase 1".
