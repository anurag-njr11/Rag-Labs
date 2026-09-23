# Frontend foundation — reference for feature agents

Built by the frontend-foundation agent. `npm run build` passes; `npx oxlint` 0 errors.
Import from `@/…` (alias for `src/`). Never re-implement anything listed here — if you need a
change, report it.

## Routes (all lazy-loaded)
`/` ProjectsPage · `/new` CreateWizard · `/projects/:id` → redirects to `documents` ·
`/projects/:id/{documents,configure,versions,playground,api}` · `*` 404.

## `@/api/types`
Mirrors every type in `API.md` exactly: `Slot, Effect, NodeConfig, PipelineConfig,
PipelineFieldError, JSONSchema, JSONSchemaProperty` (incl. `enum_labels, widget, advanced,
options_from, effect, $defs, anyOf, $ref`), `SlotCatalog, NodeType, IndexStatus,
IndexStatusValue, BuildStats, Version, Project, ProjectSummary, Change, CreateProjectBody,
UpdateProjectBody, ValidateResult, Estimate, EstimateResult, VersionDiff, CreateVersionBody,
CreateVersionResult, VersionJobResult, Build, Document, ParseQuality, UploadResult, AddUrlBody,
Chunk, ChunksResult, JobStage, JobEvent, JobDoneResult, Job, FoundBy, RetrievedChunk, Citation,
TraceStep, TraceStepName, ChatTotals, ChatEvent, ChatBody ({question, version_id?}), ChatSource,
ChatResult, RunSummary, RunDetail, Health, Provider, ModelList, ModelKind`.
Constants: `SLOTS` (pipeline order), `JOB_STAGES`, `ACCEPTED_EXTENSIONS`, `MAX_UPLOAD_BYTES`.

## `@/api/client`
- `class ApiError extends Error {status, detail, code: string|null, fieldErrors: PipelineFieldError[]}` —
  message from `detail` (string / `detail.message` / FastAPI list). 422 pipeline errors → `fieldErrors`;
  chat 409/502 → `code`. Network failure → status 0, "Cannot reach the backend…".
- `errorMessage(err: unknown): string`
- `request<T>(path, {method, body, query, signal, headers})` (JSON unless FormData; 204 → undefined)
- `api.get<T>(path, query?, signal?)`, `api.post<T>(path, body?, query?)`, `api.patch<T>(path, body?)`, `api.del(path)`
- `buildUrl(path, query?)`, `throwIfNotOk(res)`, `API_BASE`

## `@/api/sse` (re-exported from `@/api/hooks`)
- `streamChat(projectId, body: ChatBody, {onEvent, signal?}): Promise<ChatEvent | null>` — POST with
  `stream:true`, fetch-stream reader; resolves with terminal `done`/`error` event (or null);
  throws `ApiError` on non-2xx, `AbortError` on abort.
- `subscribeJobEvents(jobId, {onEvent, onReset?, onLost?}): {close}` — EventSource, auto-closes on
  done/failed; reconnect replays history (hence `onReset`).
- `class SseParser(onMessage)` `.push(chunk)` / `.flush()` — tested against every chunk split, CRLF/CR/LF.

## `@/api/hooks`
Query keys: `qk.*`. `invalidateProject(qc, projectId)`.

**Queries** (optional RQ options last; disabled until ids set): `useHealth()`, `useProviders()`,
`useNoProviderKey(): boolean|undefined`, `useProviderModels(name, kind='chat')`,
`useOptionsFrom(url)` (waits until no `{…}` placeholders remain), `fillOptionsFrom(template, values)`
(`{type}` = node type), `useNodes()`, `useRecommendedPipeline()`, `useProjects()` (polls 3s while
building), `useProject(id)` (polls while building / job_id set), `useVersions(projectId)` (polls while
building), `useVersion(projectId, vid)`, `useVersionDiff(projectId, a, b)` (version ids),
`useBuilds(projectId)`, `useDocuments(projectId)`, `useDocumentChunks(projectId, docId, limit=200)`,
`useJob(jobId)`, `useProjectJobs(projectId)`, `useRuns(projectId, limit=50)`, `useRun(runId)`.

**Mutations** (invalidate affected project data): `useCreateProject()` mutate(CreateProjectBody)→Project ·
`useUpdateProject(id)` · `useDeleteProject()` mutate(id) · `useValidatePipeline()` mutate(config)→ValidateResult ·
`useEstimate(projectId)` mutate(config)→EstimateResult · `useCreateVersion(projectId)`
mutate(CreateVersionBody)→{version, job_id, unchanged} · `useActivateVersion(projectId)` mutate(vid) ·
`useRollbackVersion(projectId)` mutate(vid) · `useBuildVersion(projectId)` mutate(vid)→{job_id} (409 if no docs) ·
`useUploadDocuments(projectId)` mutate({files, build?=true})→UploadResult · `useAddUrl(projectId)`
mutate({url, sitemap?, max_pages?})→{job_id} · `useDeleteDocument(projectId)` mutate(docId) (optimistic) ·
`useReindexDocument(projectId)` mutate(docId)→{job_id} · `useChat(projectId)` (non-streaming)→ChatResult.

**Jobs:** `useJobEvents(jobId|null, {projectId?, onDone?, onFailed?}): JobEventsState` —
`{status: 'idle'|'running'|'done'|'failed'|'lost', stages: Partial<Record<JobStage, StageProgress>>,
currentStage, logs, result, error, events}`; `StageProgress = {stage, done, total, message,
state: 'upcoming'|'running'|'done'|'failed'}` (`total: 0` = indeterminate). Invalidates project
queries when the job ends.

## `@/api/format`
`formatNumber, formatBytes, formatMs, formatCost, formatRelative(iso), formatDateTime(iso),
formatPages(start, end?), shortHash(h, n=6), humanize('vector_store'), formatValue(v),
fileExt, fileTypeLabel, storeLabel('faiss') → "FAISS"`.

## `@/components/ui` (barrel)
- `cn(...)`, `Spinner {size?=16, label?}`
- `Button {variant?: primary|secondary|ghost|danger, size?: md|sm, icon?, iconRight?, loading?, iconOnly?}`,
  `ButtonLink` (+ router LinkProps), `buttonClasses(...)`
- `Badge {tone?: neutral|accent|success|info|warning|danger|instant|rebuild|dense|keyword|exact|storeExact|storeApprox, dot?, icon?}`
- `EffectBadge {effect, count?, compact?}`, `ExactBadge {exact, label?}`, `FoundByBadge {path, children?}`,
  `StatusBadge {status, label?, withIcon?}`, `QualityBadge {score}`, `ChunkStateBadge {state: in_context|cited|dropped}`,
  `ScoreChip {kind: dense|keyword|exact|fused|rerank, value, digits?}`
- `Card {interactive?, selected?, padding?: none|sm|md|lg}`, `cardClasses(...)`, `CardHeader {title, description?, actions?}`
- `OptionCardGroup {items: {value, title, description?, badges?, disabled?, reason?}[], value, onChange, 'aria-label'}` (radio cards, arrow keys, disabled shows lock + reason)
- `Tabs {items: {value, label, icon?, count?, disabled?}[], value, onChange, variant?: segment|underline, size?, fill?, idPrefix?}`, `tabPanelProps(idPrefix, value)`, `TabLinks {items: {to, label, icon?, end?}[]}`
- `Field {label, badge?, help?, error?, aside?, inline?, id?, children: ({id, describedBy, invalid}) => ReactNode}`
- `Input {icon?, suffix?, invalid?, mono?, size?}`, `Textarea {invalid?, mono?, rows?=4}`,
  `Select {options: {value, label, disabled?}[], invalid?, size?, placeholder?}`,
  `Combobox {value, onChange(string), options: string[], loading?, id?}` (free text + suggestions, for `options_from`),
  `Switch`/`Toggle {checked, onChange(bool)}`,
  `Slider {value, onChange, min, max, step?, integer?, unit?, id?, disabled?, invalid?, hideBounds?}` (range + number box; `id` is on the number input)
- `Tooltip {content, children, placement?}`, `HoverCard {trigger, children, placement?, align?, width?=300}` (trigger must be non-interactive, e.g. a Badge),
  `Popover {open, onClose, anchor: RefObject, children, placement?, align?, width?}`,
  `Dialog {open, onClose, title, description?, children?, footer?, size?: sm|md|lg|xl, dismissible?}` — all portal-rendered
- `ToastProvider` (mounted), `useToast(): {toast({title, description?, tone?, duration?, action?}), dismiss(id)}`
- `ProgressBar {value?: 0–1|null, tone?}`, `Stepper {steps: {label}[], current (0-based), onStepClick?}`
- `CodeBlock {code, title?, noCopy?, wrap?, maxHeight?}`, `CopyButton {text, label?}`, `copyText(text)`
- `EmptyState {icon?, title, description?, actions?}`, `Banner {tone?, title?, children, actions?, variant?: inline|bar, icon?}`,
  `Disclosure {label, hint?, defaultOpen?, open?, onOpenChange?, children}` (for "Advanced · N more"), `VisuallyHidden`
- `CitationChip {n, active?}`, `SourceChip {document, meta?}`, `Pill {icon?, dotClassName?}`

## `@/app`
- `AppLayout` (52px sticky top bar, theme toggle, `<main id="main">`), `PageFallback`, `TOPBAR_H`, `BACKEND_DOCS_URL`
- `WorkspaceLayout` — provider-key banner, breadcrumb, name, pills ("v1 · active", "Index ready · 517 chunks · FAISS"),
  "Rebuild index" button, TabLinks. Handles 404/error itself.
- `useWorkspace(): {project}` (from `@/app/workspace`) — inside tabs the project is always loaded;
  also `useProjectId()`, `projectPath(id, tab)`, `WorkspaceTab`.
- `JobProgress {jobId, projectId?, showFetch?, variant?: full|compact, title?, onDone?(result), onFailed?(error)}` — per-stage rows, error box, stats, collapsible log; `STAGE_LABELS`.
- `ProviderKeyBanner {variant?: bar|inline}` (renders nothing when a provider is available), `useTheme()`.

## Must-knows
1. Tabs render inside a `flex min-h-0 flex-1 flex-col` wrapper with no padding; use `px-4 py-6 sm:px-8` for gutters.
   Playground panes: `h-[calc(100dvh-var(--chrome-h))]` (`--chrome-h` is measured live). Only the top bar is sticky —
   sticky elements use `top-[calc(var(--topbar-h)+16px)]`.
2. Chat and job SSE `data` both carry `type`. With no LLM key, chat ends with an `error` event
   ("Add GEMINI_API_KEY to .env…") — show verbatim.
3. Demo project config: structure_aware chunking, fastembed bge-small, FAISS Flat, fused retrieval, no rerank, gemini.
   `summary.model` is `""` = provider default → display `Provider.default_model`.
4. Building an up-to-date version returns a job that emits only `ready` ("Index is up to date") then `done`.
5. Query `staleTime` 10s; 4xx not retried. Pass `projectId` to `useJobEvents`/`JobProgress` so queries refresh.
6. Theme via `<html class="dark">`. Use token classes only (`bg-bg-surface`, `text-text-secondary`, `bg-rebuild-bg`, …) — never hard-coded colors.
