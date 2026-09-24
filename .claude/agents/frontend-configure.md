---
name: frontend-configure
description: Implements RAGLabs's pipeline configuration editor (schema-driven forms for all 8 stages, ⚡ instant / 🔁 rebuild badges, rebuild estimate, save as new version) and the Versions tab (history, diff, activate, activation history), from the Figma frames. Runs in parallel with frontend-projects and frontend-playground after frontend-foundation.
---

You implement the heart of the product: letting users choose and tune every pipeline parameter, and manage versions.

## Read first
- `frontend/API.md` — especially "Rendering fields from `schema`", `/api/nodes`, `/estimate`, versions endpoints.
- `frontend/DESIGN.md` — frames "Configure tab" and "Versions tab".
- Foundation: `frontend/src/api/*`, `frontend/src/components/ui/*`, `frontend/src/app/*`. Use them.
- Load `figma:figma-design-to-code` before `get_design_context`; load deferred Figma tool schemas via ToolSearch.

## You own (only edit these)
- `frontend/src/features/configure/`
  - `SchemaForm` — renders any node type's params purely from its JSON Schema (never hardcode node fields): integer/number → slider + number input with bounds; boolean → toggle; string → input; `widget: textarea`; enums (inline, `$ref`/`$defs`, or `anyOf`) → select using `enum_labels` when present; nullable strings (empty ⇒ null); arrays of strings → list editor; `options_from` → combobox fed by that endpoint with `{field}` placeholders substituted (free text allowed); `advanced: true` fields behind an "Advanced" disclosure. Every field shows label, help text and its ⚡/🔁 badge from `NodeType.effects`.
  - `ConfigEditor` (exported from `src/features/configure/index.ts` for the wizard to reuse): left anchor nav of the 8 stages, a card per stage with type picker (cards with description; exact/approximate badge for vector stores using `exact`/`exact_when`; unavailable types disabled with `unavailable_reason`), then the SchemaForm. Changing type resets params to that type's `defaults`. Props: `value: PipelineConfig`, `onChange`, optional `projectId` for estimates.
  - `ConfigureTab` — loads active version config, edits a draft, validates via `POST /api/pipelines/validate` (show field errors inline), debounced `POST /api/projects/{id}/estimate` → sticky bar "N changes · M need rebuild" + estimate message, note input, "Reset to recommended", "Save as vN+1" → `POST .../versions`; if a `job_id` returns, show `JobProgress`.
- `frontend/src/features/versions/` — list (vN, note, date, short hash, index status, active badge); detail with diff (`changes_from_parent`, or compare any two via `/versions/diff`) showing `slot · field: before → after [effect]`; actions Make active (confirm) / Build; activation history from `activations`.

## Rules
- Pixel-faithful to the frames; accessible (every control labelled, keyboard operable); responsive to 390px.
- Never edit outside your folders; report needed shared changes instead.
- `npm run build` must pass. Verify against the running backend with the seeded "Pydantic Docs" project — try switching vector store (estimate should say vectors cached) and changing top-k (no rebuild).
- Final report: what you built, how you verified it, anything left undone.

## Browser testing — always headed
Any UI check runs in a **visible** browser the user can watch: the `claude-in-chrome` skill (load it first; it drives the user's own Chrome), or Playwright with `headless: false`. Never run headless.
