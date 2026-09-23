---
name: frontend-projects
description: Implements the RAG Builder Projects list, the 4-step Create wizard (Name → Documents → Configure → Build), and the Documents tab, from the Figma frames. Runs in parallel with frontend-configure and frontend-playground after frontend-foundation has finished.
---

You implement three screens of RAG Builder from their Figma frames, against the real backend.

## Read first
- `frontend/API.md` (backend contract), `frontend/DESIGN.md` (tokens, frame names + node ids).
- The foundation layer: `frontend/src/api/*` (types, client, SSE helpers, hooks) and `frontend/src/components/ui/*`, `frontend/src/app/*`. Use these — do not re-implement them.
- Load the `figma:figma-design-to-code` skill before calling `get_design_context`; load deferred Figma tool schemas with ToolSearch. Fetch your frames: "Projects", "Projects — empty", "Create — Documents", "Create — Build", "Documents tab".

## You own (only edit these)
- `frontend/src/features/projects/` — projects grid with cards (name, description, docs, chunks, store, model, updated, index status), empty state, delete with confirm.
- `frontend/src/features/wizard/` — stepper. Step 1 name/description → `POST /api/projects`. Step 2 upload (drag-and-drop, multiple files, type/size validation matching API.md) + URL / sitemap form; upload with `?build=false` so nothing builds before configuring. Step 3 embeds the Configure editor exported by `src/features/configure/` (import `ConfigEditor` from `@/features/configure`; if it doesn't exist yet, render a "Use recommended settings" summary with a TODO and report it). Save config via `POST /api/projects/{id}/versions`. Step 4 build: trigger `POST .../versions/{vid}/build`, show `JobProgress`, finish → Playground.
- `frontend/src/features/documents/` — table: filename + type icon, size, status, chunks (active index), parse-quality badge with hover card (warnings, pages, tables, header lines removed), row actions Re-index / Delete (confirm), header actions Upload files / Add URL (sitemap toggle + max pages). Show running jobs with `JobProgress`. A chunk viewer drawer (`GET .../documents/{doc}/chunks`) is a nice extra if time allows.

## Rules
- Pixel-faithful to the frames, using tokens and shared primitives; accessible; responsive to 390px.
- Handle loading, empty, error (show API `detail` text) and in-progress states everywhere.
- Never edit files outside your folders. If you need a shared change (new primitive, hook, type), note it in your final report instead of making it.
- `npm run build` must pass before you finish. Verify manually against the running backend (`cd backend && uv run uvicorn app.main:app`, `cd frontend && npm run dev`).
- Final report: what you built, how you verified it, anything left undone, shared changes you need.

## Browser testing — always headed
Any UI check runs in a **visible** browser the user can watch: the `claude-in-chrome` skill (load it first; it drives the user's own Chrome), or Playwright with `headless: false`. Never run headless.
