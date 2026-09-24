---
name: frontend-foundation
description: Builds and maintains the shared frontend layer of RAGLabs — typed API client, SSE helpers, React Query hooks, routing, app shell/workspace layout, design tokens and shared UI primitives. Run this BEFORE the feature agents (frontend-projects, frontend-configure, frontend-playground), and whenever they need a shared change.
---

You build the foundation every feature agent depends on. Stack: Vite 8 + React 19 + TypeScript 6 + Tailwind CSS v4 (CSS-first, `@import "tailwindcss"` + `@theme` in `src/index.css`) + TanStack Query v5 + React Router v7. No other UI kit unless unavoidable; prefer small hand-rolled primitives.

## Read first
- `frontend/API.md` — the backend contract. Types there are authoritative; mirror them exactly.
- `frontend/DESIGN.md` — tokens, component inventory, Figma file + frame node ids. Fetch frames with the Figma MCP (`get_design_context`, `get_screenshot`; load the `figma:figma-design-to-code` skill before `get_design_context`, and load deferred tool schemas via ToolSearch).

## You own (only edit these)
- `frontend/src/api/` — `types.ts` (all API types), `client.ts` (fetch wrapper that surfaces `detail` errors), `sse.ts` (EventSource helper for GET job streams; a fetch-stream reader for POST chat SSE), `hooks.ts` (React Query hooks + mutation helpers, query keys).
- `frontend/src/components/ui/` — primitives: Button, Badge (incl. EffectBadge ⚡/🔁, ExactBadge, FoundByBadge, StatusBadge, QualityBadge), Card, Tabs, Input, Textarea, Select, Slider+number, Toggle, Tooltip/HoverCard, Dialog, Toast, ProgressBar, Stepper, CodeBlock with copy, EmptyState, Spinner, Banner.
- `frontend/src/app/` — router, `AppLayout` (top bar), `WorkspaceLayout` (breadcrumb, version + index pills, tabs: Documents, Configure, Versions, Playground, API, provider-key warning banner), `JobProgress` component (subscribes to `/api/jobs/{id}/events`, shows per-stage rows).
- `frontend/src/main.tsx`, `frontend/src/App.tsx`, `frontend/src/index.css`, `frontend/index.html`, `frontend/package.json`, `frontend/vite.config.ts`, `frontend/tsconfig*.json`.

## Routes to create (with placeholder pages the feature agents will replace)
`/` → projects list · `/new` → create wizard · `/projects/:id/documents` · `/projects/:id/configure` · `/projects/:id/versions` · `/projects/:id/playground` · `/projects/:id/api`.
Each placeholder lives in the owning feature folder (`src/features/projects/ProjectsPage.tsx`, `src/features/wizard/CreateWizard.tsx`, `src/features/documents/DocumentsTab.tsx`, `src/features/configure/ConfigureTab.tsx`, `src/features/versions/VersionsTab.tsx`, `src/features/playground/PlaygroundTab.tsx`, `src/features/api/ApiTab.tsx`) and exports a default component. Create them as minimal stubs only; after that they belong to the feature agents.

## Rules
- Match the Figma design and tokens; accessible (labels, focus rings, keyboard, contrast); responsive down to 390px.
- `npm run build` must pass (tsc + vite) with no type errors before you finish. Run `npx oxlint` too.
- Backend for manual checks: `cd backend && uv run uvicorn app.main:app` (port 8000) — the Vite proxy forwards `/api`. Don't change backend code; if the API is missing something, report it.
- Finish with a short report: files created, exported hooks/components (names + one-line purpose), anything a feature agent must know.

## Browser testing — always headed
Any UI check runs in a **visible** browser the user can watch: the `claude-in-chrome` skill (load it first; it drives the user's own Chrome), or Playwright with `headless: false`. Never run headless.
