/** React Query hooks for every endpoint in API.md, plus job-event and chat-stream helpers. */
import { useEffect, useRef, useState } from 'react'
import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
  type UseQueryOptions,
} from '@tanstack/react-query'
import { api, buildUrl } from './client'
import { subscribeJobEvents } from './sse'
import type {
  AddUrlBody,
  ChatBody,
  ChatResult,
  ChunksResult,
  CreateProjectBody,
  CreateVersionBody,
  CreateVersionResult,
  Document,
  DocumentOkf,
  EstimateResult,
  EvalRun,
  InjectionRun,
  Adapter,
  ConfigPrior,
  Recipe,
  BuildChatResult,
  ApiKey,
  UsageReport,
  HealthMonitor,
  Computation,
  ComputationSpec,
  ComputeReceipt,
  DataTable,
  OkfImportResult,
  PromptRun,
  EvalRunDetail,
  ExternalConfig,
  ExternalSystem,
  ExternalTestResult,
  EvalSet,
  EvalSetDetail,
  Sweep,
  SweepAxes,
  EvalFix,
  Judge,
  HealthReport,
  Job,
  JobDoneResult,
  JobEvent,
  JobStage,
  ModelKind,
  ModelList,
  PipelineConfig,
  Project,
  Provider,
  ProviderInput,
  ProviderTestResult,
  RunDetail,
  RunSummary,
  SlotCatalog,
  Suggestions,
  UpdateProjectBody,
  UploadResult,
  ValidateResult,
  Version,
  VersionDiff,
  VersionJobResult,
} from './types'

export { streamChat, subscribeJobEvents, SseParser } from './sse'
export type { StreamChatOptions } from './sse'
export { ApiError, errorMessage, api } from './client'

// ------------------------------------------------------------------------------------------ query keys

export const qk = {
  health: ['health'] as const,
  providers: ['providers'] as const,
  providerPresets: ['providers', 'presets'] as const,
  providerModels: (name: string, kind: ModelKind) => ['providers', name, 'models', kind] as const,
  nodes: ['nodes'] as const,
  recommended: ['pipelines', 'recommended'] as const,
  projects: ['projects'] as const,
  project: (id: string) => ['projects', id] as const,
  versions: (id: string) => ['projects', id, 'versions'] as const,
  version: (id: string, vid: string) => ['projects', id, 'versions', vid] as const,
  versionDiff: (id: string, a: string, b: string) => ['projects', id, 'versions', 'diff', a, b] as const,
  builds: (id: string) => ['projects', id, 'builds'] as const,
  documents: (id: string) => ['projects', id, 'documents'] as const,
  chunks: (id: string, docId: string, limit: number) => ['projects', id, 'documents', docId, 'chunks', limit] as const,
  projectJobs: (id: string) => ['projects', id, 'jobs'] as const,
  runs: (id: string, limit: number) => ['projects', id, 'runs', limit] as const,
  suggestions: (id: string) => ['projects', id, 'suggestions'] as const,
  job: (jobId: string) => ['jobs', jobId] as const,
  run: (runId: string) => ['runs', runId] as const,
  evalSets: (id: string) => ['projects', id, 'eval', 'sets'] as const,
  evalSet: (id: string, setId: string) => ['projects', id, 'eval', 'sets', setId] as const,
  external: (id: string) => ['projects', id, 'external'] as const,
  evalRuns: (id: string, setId: string) => ['projects', id, 'eval', 'runs', setId] as const,
  evalRun: (id: string, runId: string) => ['projects', id, 'eval', 'run', runId] as const,
  evalFixes: (id: string, runId: string) => ['projects', id, 'eval', 'run', runId, 'fixes'] as const,
  sweeps: (id: string) => ['projects', id, 'eval', 'sweeps'] as const,
  injection: (id: string) => ['projects', id, 'eval', 'injection'] as const,
  adapters: (id: string) => ['projects', id, 'eval', 'adapters'] as const,
  promptRuns: (id: string) => ['projects', id, 'eval', 'prompt-runs'] as const,
  sweepAxes: (id: string) => ['projects', id, 'eval', 'sweep-axes'] as const,
  healthReports: (id: string) => ['projects', id, 'health'] as const,
  healthReport: (id: string, rid: string) => ['projects', id, 'health', rid] as const,
}

/** Invalidate everything under a project (project, versions, documents, builds, jobs, runs) + the list. */
export function invalidateProject(qc: QueryClient, projectId: string) {
  void qc.invalidateQueries({ queryKey: qk.project(projectId) })
  void qc.invalidateQueries({ queryKey: qk.projects, exact: true })
}

type QOpts<T> = Omit<UseQueryOptions<T, Error, T, readonly unknown[]>, 'queryKey' | 'queryFn'>

const isBusy = (s?: string) => s === 'building' || s === 'pending'

// ------------------------------------------------------------------------------------------ system

export const useProviders = (o?: QOpts<Provider[]>) =>
  useQuery({ queryKey: qk.providers, queryFn: () => api.get<Provider[]>('/providers'), staleTime: 60_000, ...o })

export const useProviderPresets = (o?: QOpts<Provider[]>) =>
  useQuery({ queryKey: qk.providerPresets, queryFn: () => api.get<Provider[]>('/providers/presets'), staleTime: 60_000, ...o })

/** Provider changes add/remove Generate node types, so the catalog and health refresh too. */
function invalidateProviders(qc: QueryClient) {
  void qc.invalidateQueries({ queryKey: qk.providers })
  void qc.invalidateQueries({ queryKey: qk.nodes })
  void qc.invalidateQueries({ queryKey: qk.health })
  void qc.invalidateQueries({ queryKey: qk.recommended })
  void qc.invalidateQueries({ queryKey: ['options_from'] })
}

/** Create (`create: true`) or update a provider. */
export function useSaveProvider() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ name, body, create }: { name: string; body: ProviderInput; create?: boolean }) =>
      create
        ? api.post<Provider>('/providers', { ...body, name })
        : api.patch<Provider>(`/providers/${encodeURIComponent(name)}`, body),
    onSuccess: () => invalidateProviders(qc),
  })
}

export function useDeleteProvider() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (name: string) => api.del(`/providers/${encodeURIComponent(name)}`),
    onSuccess: () => invalidateProviders(qc),
  })
}

/** Test saved settings (`name` only) or a draft (`body`, falling back to the named provider's settings). */
export const useTestProvider = () =>
  useMutation({
    mutationFn: ({ name, body }: { name?: string; body?: ProviderInput }) =>
      body
        ? api.post<ProviderTestResult>('/providers/test', { ...body, name })
        : api.post<ProviderTestResult>(`/providers/${encodeURIComponent(name ?? '')}/test`),
  })

export const useProviderModels = (name: string | undefined, kind: ModelKind = 'chat', o?: QOpts<ModelList>) =>
  useQuery({
    queryKey: qk.providerModels(name ?? '', kind),
    queryFn: () => api.get<ModelList>(`/providers/${name}/models`, { kind }),
    enabled: !!name,
    staleTime: 5 * 60_000,
    ...o,
  })

/**
 * Options for a schema `options_from` URL, e.g. "/api/providers/{provider}/models?kind=embed".
 * Pass the URL with `{field}` placeholders already substituted (see `fillOptionsFrom`).
 */
export const useOptionsFrom = (url: string | null | undefined, o?: QOpts<ModelList>) =>
  useQuery({
    queryKey: ['options_from', url ?? ''],
    queryFn: () => api.get<ModelList>(url!),
    enabled: !!url && !url.includes('{'),
    staleTime: 5 * 60_000,
    ...o,
  })

/** Substitute `{field}` placeholders in an `options_from` template from the node's values (`{type}` = node type). */
export function fillOptionsFrom(template: string, values: Record<string, unknown>): string {
  return template.replace(/\{(\w+)\}/g, (m, k: string) => {
    const v = values[k]
    return v === undefined || v === null || v === '' ? m : encodeURIComponent(String(v))
  })
}

// ------------------------------------------------------------------------------------------ pipeline catalog

export const useNodes = (o?: QOpts<SlotCatalog[]>) =>
  useQuery({ queryKey: qk.nodes, queryFn: () => api.get<SlotCatalog[]>('/nodes'), staleTime: 5 * 60_000, ...o })

export const useRecommendedPipeline = (o?: QOpts<PipelineConfig>) =>
  useQuery({
    queryKey: qk.recommended,
    queryFn: () => api.get<PipelineConfig>('/pipelines/recommended'),
    staleTime: Infinity,
    ...o,
  })

export interface SmartRecommendation {
  config: PipelineConfig
  reasoning: Record<string, string>
  metadata: {
    corpus_size: number
    estimated_chunks: number
    languages: string[]
    domains: string[]
    confidence: number
  }
}

export const useSmartRecommend = (projectId: string | undefined) =>
  useQuery({
    queryKey: ['recommend', projectId],
    queryFn: () => api.post<SmartRecommendation>(`/projects/${projectId}/recommend`, {}),
    enabled: !!projectId,
    staleTime: 5 * 60_000,
  })

export const useValidatePipeline = () =>
  useMutation({ mutationFn: (config: PipelineConfig) => api.post<ValidateResult>('/pipelines/validate', { config }) })

// ------------------------------------------------------------------------------------------ projects

export const useProjects = (o?: QOpts<Project[]>) =>
  useQuery({
    queryKey: qk.projects,
    queryFn: () => api.get<Project[]>('/projects'),
    // Keep cards live while any index builds.
    refetchInterval: (q) => (q.state.data?.some((p) => isBusy(p.index?.status) || p.index?.job_id) ? 3000 : false),
    ...o,
  })

export const useProject = (id: string | undefined, o?: QOpts<Project>) =>
  useQuery({
    queryKey: qk.project(id ?? ''),
    queryFn: () => api.get<Project>(`/projects/${id}`),
    enabled: !!id,
    refetchInterval: (q) => (isBusy(q.state.data?.index?.status) || q.state.data?.index?.job_id ? 3000 : false),
    ...o,
  })

export function useCreateProject() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: CreateProjectBody) => api.post<Project>('/projects', body),
    onSuccess: (p) => {
      qc.setQueryData(qk.project(p.id), p)
      void qc.invalidateQueries({ queryKey: qk.projects, exact: true })
    },
  })
}

export function useUpdateProject(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: UpdateProjectBody) => api.patch<Project>(`/projects/${id}`, body),
    onSuccess: (p) => {
      qc.setQueryData(qk.project(id), p)
      void qc.invalidateQueries({ queryKey: qk.projects, exact: true })
    },
  })
}

export function useDeleteProject() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.del(`/projects/${id}`),
    onSuccess: (_d, id) => {
      qc.removeQueries({ queryKey: qk.project(id) })
      void qc.invalidateQueries({ queryKey: qk.projects, exact: true })
    },
  })
}

// ------------------------------------------------------------------------------------------ versions & builds

export const useEstimate = (projectId: string) =>
  useMutation({
    mutationFn: (config: PipelineConfig) => api.post<EstimateResult>(`/projects/${projectId}/estimate`, { config }),
  })

export const useVersions = (projectId: string | undefined, o?: QOpts<Version[]>) =>
  useQuery({
    queryKey: qk.versions(projectId ?? ''),
    queryFn: () => api.get<Version[]>(`/projects/${projectId}/versions`),
    enabled: !!projectId,
    refetchInterval: (q) => (q.state.data?.some((v) => isBusy(v.index?.status)) ? 3000 : false),
    ...o,
  })

export const useVersion = (projectId: string | undefined, vid: string | undefined, o?: QOpts<Version>) =>
  useQuery({
    queryKey: qk.version(projectId ?? '', vid ?? ''),
    queryFn: () => api.get<Version>(`/projects/${projectId}/versions/${vid}`),
    enabled: !!projectId && !!vid,
    ...o,
  })

/** Diff a → b (both version ids). */
export const useVersionDiff = (projectId: string | undefined, a: string | undefined, b: string | undefined, o?: QOpts<VersionDiff>) =>
  useQuery({
    queryKey: qk.versionDiff(projectId ?? '', a ?? '', b ?? ''),
    queryFn: () => api.get<VersionDiff>(`/projects/${projectId}/versions/diff`, { a, b }),
    enabled: !!projectId && !!a && !!b,
    ...o,
  })

export function useCreateVersion(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: CreateVersionBody) => api.post<CreateVersionResult>(`/projects/${projectId}/versions`, body),
    onSuccess: () => invalidateProject(qc, projectId),
  })
}

export function useActivateVersion(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (vid: string) => api.post<VersionJobResult>(`/projects/${projectId}/versions/${vid}/activate`),
    onSuccess: () => invalidateProject(qc, projectId),
  })
}

/** 409 if the project has no documents. */
export function useBuildVersion(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (vid: string) => api.post<{ job_id: string }>(`/projects/${projectId}/versions/${vid}/build`),
    onSuccess: () => invalidateProject(qc, projectId),
  })
}

// ------------------------------------------------------------------------------------------ documents

export const useDocuments = (projectId: string | undefined, o?: QOpts<Document[]>) =>
  useQuery({
    queryKey: qk.documents(projectId ?? ''),
    queryFn: () => api.get<Document[]>(`/projects/${projectId}/documents`),
    enabled: !!projectId,
    ...o,
  })

export const useDocumentChunks = (projectId: string | undefined, docId: string | undefined, limit = 200, o?: QOpts<ChunksResult>) =>
  useQuery({
    queryKey: qk.chunks(projectId ?? '', docId ?? '', limit),
    queryFn: () => api.get<ChunksResult>(`/projects/${projectId}/documents/${docId}/chunks`, { limit }),
    enabled: !!projectId && !!docId,
    placeholderData: keepPreviousData,
    ...o,
  })

/** Import an OKF bundle (zip of Markdown with front matter) as documents (FR-3.18). */
export function useImportOkf(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (file: File) => {
      const fd = new FormData()
      fd.append('file', file, file.name)
      return api.post<OkfImportResult>(`/projects/${projectId}/documents/okf`, fd)
    },
    onSuccess: () => invalidateProject(qc, projectId),
  })
}

export function useUploadDocuments(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ files, build = true }: { files: File[] | FileList; build?: boolean }) => {
      const fd = new FormData()
      for (const f of Array.from(files)) {
        fd.append('files', f, f.name)
        fd.append('last_modified', String(f.lastModified || 0)) // one per file, same order; 0 = unknown
      }
      return api.post<UploadResult>(`/projects/${projectId}/documents`, fd, { build })
    },
    onSuccess: () => invalidateProject(qc, projectId),
  })
}

/** 202 {job_id} — the job fetches pages, then builds. */
export function useAddUrl(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: AddUrlBody) => api.post<{ job_id: string }>(`/projects/${projectId}/documents/url`, body),
    onSuccess: () => invalidateProject(qc, projectId),
  })
}

/** Replace a document's OKF fields. Not index config: never rebuilds. */
export function useUpdateDocumentMetadata(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ docId, okf }: { docId: string; okf: DocumentOkf }) =>
      api.patch<Document>(`/projects/${projectId}/documents/${docId}/metadata`, okf),
    onSuccess: (doc) => qc.setQueryData<Document[]>(qk.documents(projectId), (prev) => prev?.map((d) => (d.id === doc.id ? doc : d))),
  })
}

export function useDeleteDocument(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (docId: string) => api.del(`/projects/${projectId}/documents/${docId}`),
    onMutate: async (docId) => {
      await qc.cancelQueries({ queryKey: qk.documents(projectId) })
      const prev = qc.getQueryData<Document[]>(qk.documents(projectId))
      if (prev) qc.setQueryData(qk.documents(projectId), prev.filter((d) => d.id !== docId))
      return { prev }
    },
    onError: (_e, _id, ctx) => {
      if (ctx?.prev) qc.setQueryData(qk.documents(projectId), ctx.prev)
    },
    onSettled: () => invalidateProject(qc, projectId),
  })
}

export function useReindexDocument(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (docId: string) => api.post<{ job_id: string }>(`/projects/${projectId}/documents/${docId}/reindex`),
    onSuccess: () => invalidateProject(qc, projectId),
  })
}

// ------------------------------------------------------------------------------------------ jobs

/** Running jobs for a project. Polls every 3s while any are running. */
export const useProjectJobs = (projectId: string | undefined, o?: QOpts<Job[]>) =>
  useQuery({
    queryKey: qk.projectJobs(projectId ?? ''),
    queryFn: () => api.get<Job[]>(`/projects/${projectId}/jobs`),
    enabled: !!projectId,
    refetchInterval: (q) => (q.state.data?.length ? 3000 : false),
    ...o,
  })

export interface StageProgress {
  stage: JobStage
  done: number
  /** 0 = indeterminate */
  total: number
  message: string
  state: 'upcoming' | 'running' | 'done' | 'failed'
}
export type JobStreamStatus = 'idle' | 'running' | 'done' | 'failed' | 'lost'
export interface JobEventsState {
  status: JobStreamStatus
  /** Per-stage progress, keyed by stage (only stages that have reported). */
  stages: Partial<Record<JobStage, StageProgress>>
  /** Latest stage that reported progress. */
  currentStage: JobStage | null
  logs: Extract<JobEvent, { type: 'log' }>[]
  result: JobDoneResult | null
  error: string | null
  events: JobEvent[]
}
export interface UseJobEventsOptions {
  /** Project to invalidate when the job finishes (defaults to the job's own project via GET /jobs/{id} — pass it when known). */
  projectId?: string
  onDone?: (result: JobDoneResult) => void
  onFailed?: (error: string) => void
}

const EMPTY_JOB_STATE: JobEventsState = {
  status: 'idle', stages: {}, currentStage: null, logs: [], result: null, error: null, events: [],
}

function reduceJob(s: JobEventsState, e: JobEvent): JobEventsState {
  const events = [...s.events, e]
  switch (e.type) {
    case 'progress': {
      const stages = { ...s.stages }
      // Everything reported before this stage is complete.
      for (const k of Object.keys(stages) as JobStage[]) {
        if (k !== e.stage && stages[k]!.state === 'running') stages[k] = { ...stages[k]!, state: 'done' }
      }
      const finished = e.stage === 'ready' || (e.total > 0 && e.done >= e.total)
      stages[e.stage] = { stage: e.stage, done: e.done, total: e.total, message: e.message, state: finished ? 'done' : 'running' }
      return { ...s, status: 'running', stages, currentStage: e.stage, events }
    }
    case 'log':
      return { ...s, status: s.status === 'idle' ? 'running' : s.status, logs: [...s.logs, e], events }
    case 'done': {
      const stages = { ...s.stages }
      for (const k of Object.keys(stages) as JobStage[]) stages[k] = { ...stages[k]!, state: 'done' }
      return { ...s, status: 'done', stages, result: e.result, events }
    }
    case 'failed': {
      const stages = { ...s.stages }
      if (s.currentStage && stages[s.currentStage]) stages[s.currentStage] = { ...stages[s.currentStage]!, state: 'failed' }
      return { ...s, status: 'failed', stages, error: e.error, events }
    }
  }
}

/**
 * Subscribe to GET /api/jobs/{jobId}/events (history replay + live). Pass null/undefined to stay idle.
 * On `done`/`failed` it closes the stream and invalidates project queries.
 */
export function useJobEvents(jobId: string | null | undefined, opts: UseJobEventsOptions = {}): JobEventsState {
  const qc = useQueryClient()
  const [state, setState] = useState<{ jobId: string | null; s: JobEventsState }>({ jobId: null, s: EMPTY_JOB_STATE })
  const optsRef = useRef(opts)
  useEffect(() => {
    optsRef.current = opts
  })

  useEffect(() => {
    if (!jobId) return
    const sub = subscribeJobEvents(jobId, {
      onEvent: (e) => {
        setState((prev) => ({ jobId, s: reduceJob(prev.jobId === jobId ? prev.s : EMPTY_JOB_STATE, e) }))
        if (e.type === 'done' || e.type === 'failed') {
          const pid = optsRef.current.projectId
          if (pid) invalidateProject(qc, pid)
          else void qc.invalidateQueries({ queryKey: qk.projects })
          void qc.invalidateQueries({ queryKey: qk.job(jobId) })
          if (e.type === 'done') optsRef.current.onDone?.(e.result)
          else optsRef.current.onFailed?.(e.error)
        }
      },
      onReset: () => setState({ jobId, s: { ...EMPTY_JOB_STATE, status: 'running' } }),
      onLost: () => {
        setState((prev) => ({ jobId, s: { ...(prev.jobId === jobId ? prev.s : EMPTY_JOB_STATE), status: 'lost' } }))
        const pid = optsRef.current.projectId
        if (pid) invalidateProject(qc, pid)
      },
    })
    return () => sub.close()
  }, [jobId, qc])

  if (!jobId) return EMPTY_JOB_STATE
  if (state.jobId !== jobId) return { ...EMPTY_JOB_STATE, status: 'running' }
  return state.s.status === 'idle' ? { ...state.s, status: 'running' } : state.s
}

// ------------------------------------------------------------------------------------------ chat & runs

/** Non-streaming chat (`stream: false`). For streaming use `streamChat`. */
export function useChat(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: ChatBody) => api.post<ChatResult>(`/projects/${projectId}/chat`, { ...body, stream: false }),
    onSettled: () => void qc.invalidateQueries({ queryKey: ['projects', projectId, 'runs'] }),
  })
}

export const useBuildChat = (projectId: string) =>
  useMutation({
    mutationFn: (body: { instruction: string; config?: PipelineConfig }) =>
      api.post<BuildChatResult>(`/projects/${projectId}/build-chat`, body),
  })

export const useConfigPrior = (projectId: string) =>
  useQuery({ queryKey: ['projects', projectId, 'config-prior'], queryFn: () => api.get<ConfigPrior>(`/projects/${projectId}/config-prior`) })

// ------------------------------------------------------------------------- recipes (FR-3.26)

export const useRecipes = () => useQuery({ queryKey: ['recipes'], queryFn: () => api.get<Recipe[]>('/recipes') })

export function useSaveRecipe() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { name: string; description?: string; tags?: string[]; config: PipelineConfig; source_project?: string }) =>
      api.post<Recipe>('/recipes', body),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['recipes'] }),
  })
}

export function useDeleteRecipe() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.del(`/recipes/${id}`),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['recipes'] }),
  })
}

/** A recipe's config made fit for a project, plus notes on what was adjusted. */
export const useForkConfig = () =>
  useMutation({
    mutationFn: ({ projectId, config }: { projectId: string; config: PipelineConfig }) =>
      api.post<{ config: PipelineConfig; notes: string[] }>(`/projects/${projectId}/recipe-config`, { config }),
  })

/** Save a version into any project (the recipe page isn't inside a workspace). */
export function useCreateVersionFor() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ projectId, body }: { projectId: string; body: CreateVersionBody }) =>
      api.post<CreateVersionResult>(`/projects/${projectId}/versions`, body),
    onSuccess: (_r, { projectId }) => invalidateProject(qc, projectId),
  })
}

// ------------------------------------------------------------------------- API keys & usage (FR-3.23)

export const useApiKeys = () => useQuery({ queryKey: ['api-keys'], queryFn: () => api.get<ApiKey[]>('/keys') })

export function useCreateApiKey() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { name: string; scope: 'chat' | 'admin'; project_id?: string }) => api.post<ApiKey & { key: string }>('/keys', body),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['api-keys'] }),
  })
}

export function useRevokeApiKey() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.del(`/keys/${id}`),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['api-keys'] }),
  })
}

export const useUsage = (projectId: string, days: number) =>
  useQuery({
    queryKey: ['projects', projectId, 'usage', days],
    queryFn: () => api.get<UsageReport>(`/projects/${projectId}/usage`, { days }),
    refetchInterval: 30_000,
  })

// ------------------------------------------------------------------------- data & computations (FR-3.21)

export const useDataTables = (projectId: string | undefined) =>
  useQuery({
    queryKey: ['projects', projectId, 'data'],
    queryFn: () => api.get<DataTable[]>(`/projects/${projectId}/data`),
    enabled: !!projectId,
  })

export function useUploadTables(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (files: File[]) => {
      const fd = new FormData()
      for (const f of files) fd.append('files', f, f.name)
      return api.post<{ created: DataTable[]; errors: { filename: string; error: string }[] }>(`/projects/${projectId}/data`, fd)
    },
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['projects', projectId, 'data'] }),
  })
}

export function useDeleteTable(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (table: string) => api.del(`/projects/${projectId}/data/${encodeURIComponent(table)}`),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['projects', projectId, 'data'] }),
  })
}

export const useComputations = (projectId: string | undefined) =>
  useQuery({
    queryKey: ['projects', projectId, 'computations'],
    queryFn: () => api.get<Computation[]>(`/projects/${projectId}/computations`),
    enabled: !!projectId,
  })

export function useSaveComputation(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, spec }: { id?: string; spec: ComputationSpec }) =>
      id ? api.put<Computation>(`/projects/${projectId}/computations/${id}`, spec)
        : api.post<Computation>(`/projects/${projectId}/computations`, spec),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['projects', projectId, 'computations'] }),
  })
}

export function useDeleteComputation(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.del(`/projects/${projectId}/computations/${id}`),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['projects', projectId, 'computations'] }),
  })
}

export const useRunComputation = (projectId: string) =>
  useMutation({
    mutationFn: ({ id, parameters }: { id: string; parameters: Record<string, unknown> }) =>
      api.post<ComputeReceipt>(`/projects/${projectId}/computations/${id}/run`, { parameters }),
  })

/** Semantic answer cache size for a project (all configurations). */
export const useCacheStats = (projectId: string | undefined) =>
  useQuery({
    queryKey: ['projects', projectId, 'cache'],
    queryFn: () => api.get<{ entries: number; hits: number }>(`/projects/${projectId}/cache`),
    enabled: !!projectId,
  })

export function useClearCache(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api.del<{ cleared: number }>(`/projects/${projectId}/cache`),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['projects', projectId, 'cache'] }),
  })
}

export const useRuns = (projectId: string | undefined, limit = 50, o?: QOpts<RunSummary[]>) =>
  useQuery({
    queryKey: qk.runs(projectId ?? '', limit),
    queryFn: () => api.get<RunSummary[]>(`/projects/${projectId}/runs`, { limit }),
    enabled: !!projectId,
    ...o,
  })

/** Starter questions drawn from the project's own eval set, section headings or recent questions. */
export const useSuggestions = (projectId: string | undefined, o?: QOpts<Suggestions>) =>
  useQuery({
    queryKey: qk.suggestions(projectId ?? ''),
    queryFn: () => api.get<Suggestions>(`/projects/${projectId}/suggestions`),
    enabled: !!projectId,
    ...o,
  })

export const useRun = (runId: string | null | undefined, o?: QOpts<RunDetail>) =>
  useQuery({
    queryKey: qk.run(runId ?? ''),
    queryFn: () => api.get<RunDetail>(`/runs/${runId}`),
    enabled: !!runId,
    staleTime: Infinity,
    ...o,
  })

// ------------------------------------------------------------------------------------------ evaluation

const evalBase = (projectId: string) => `/projects/${projectId}/eval`
const pollWhileRunning = (running: boolean) => (running ? 3000 : false)

export const useEvalSets = (projectId: string | undefined, o?: QOpts<EvalSet[]>) =>
  useQuery({
    queryKey: qk.evalSets(projectId ?? ''),
    queryFn: () => api.get<EvalSet[]>(`${evalBase(projectId!)}/sets`),
    enabled: !!projectId,
    refetchInterval: (q) => pollWhileRunning(!!q.state.data?.some((s) => s.status === 'running')),
    ...o,
  })

export const useEvalSet = (projectId: string | undefined, setId: string | null | undefined, o?: QOpts<EvalSetDetail>) =>
  useQuery({
    queryKey: qk.evalSet(projectId ?? '', setId ?? ''),
    queryFn: () => api.get<EvalSetDetail>(`${evalBase(projectId!)}/sets/${setId}`),
    enabled: !!projectId && !!setId,
    refetchInterval: (q) => pollWhileRunning(q.state.data?.status === 'running'),
    ...o,
  })

export function useGenerateEvalSet(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { size?: number; version_id?: string }) =>
      api.post<{ eval_set: EvalSet; job_id: string }>(`${evalBase(projectId)}/sets`, body),
    onSuccess: () => void qc.invalidateQueries({ queryKey: qk.evalSets(projectId) }),
  })
}

export const useEvalRuns = (projectId: string | undefined, setId: string | null | undefined, o?: QOpts<EvalRun[]>) =>
  useQuery({
    queryKey: qk.evalRuns(projectId ?? '', setId ?? ''),
    queryFn: () => api.get<EvalRun[]>(`${evalBase(projectId!)}/runs`, { set_id: setId }),
    enabled: !!projectId && !!setId,
    refetchInterval: (q) => pollWhileRunning(!!q.state.data?.some((r) => r.status === 'running')),
    ...o,
  })

export const useEvalRun = (projectId: string | undefined, runId: string | null | undefined, o?: QOpts<EvalRunDetail>) =>
  useQuery({
    queryKey: qk.evalRun(projectId ?? '', runId ?? ''),
    queryFn: () => api.get<EvalRunDetail>(`${evalBase(projectId!)}/runs/${runId}`),
    enabled: !!projectId && !!runId,
    refetchInterval: (q) => pollWhileRunning(q.state.data?.status === 'running'),
    ...o,
  })

export function useRunEval(projectId: string, setId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { version_id?: string; answers?: boolean; judge?: Judge }) =>
      api.post<{ run: EvalRun; job_id: string }>(`${evalBase(projectId)}/sets/${setId}/runs`, body),
    onSuccess: () => void qc.invalidateQueries({ queryKey: qk.evalRuns(projectId, setId) }),
  })
}

// ------------------------------------------------------------------------------------------ bring your own RAG

export const useExternalSystems = (projectId: string | undefined, o?: QOpts<ExternalSystem[]>) =>
  useQuery({
    queryKey: qk.external(projectId ?? ''),
    queryFn: () => api.get<ExternalSystem[]>(`/projects/${projectId}/external`),
    enabled: !!projectId,
    ...o,
  })

export function useCreateExternal(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { name: string; config: ExternalConfig }) =>
      api.post<ExternalSystem>(`/projects/${projectId}/external`, body),
    onSuccess: () => void qc.invalidateQueries({ queryKey: qk.external(projectId) }),
  })
}

export function useDeleteExternal(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.del(`/projects/${projectId}/external/${id}`),
    onSuccess: () => void qc.invalidateQueries({ queryKey: qk.external(projectId) }),
  })
}

export const useTestExternal = (projectId: string) =>
  useMutation({
    mutationFn: (body: { config: ExternalConfig; question?: string }) =>
      api.post<ExternalTestResult>(`/projects/${projectId}/external/test`, body),
  })

// ------------------------------------------------------------------------------------------ sweeps

export const useSweepAxes = (projectId: string | undefined) =>
  useQuery({
    queryKey: qk.sweepAxes(projectId ?? ''),
    queryFn: () => api.get<SweepAxes>(`${evalBase(projectId!)}/sweep-axes`),
    enabled: !!projectId,
    staleTime: Infinity,
  })

/** All sweeps, newest first; polls while one is running so the leaderboard fills in live. */
export const useSweeps = (projectId: string | undefined, o?: QOpts<Sweep[]>) =>
  useQuery({
    queryKey: qk.sweeps(projectId ?? ''),
    queryFn: () => api.get<Sweep[]>(`${evalBase(projectId!)}/sweeps`),
    enabled: !!projectId,
    refetchInterval: (q) => pollWhileRunning(!!q.state.data?.some((s) => s.status === 'running')),
    ...o,
  })

export const useInjectionRuns = (projectId: string | undefined) =>
  useQuery({
    queryKey: qk.injection(projectId ?? ''),
    queryFn: () => api.get<InjectionRun[]>(`${evalBase(projectId!)}/injection`),
    enabled: !!projectId,
    refetchInterval: (q) => pollWhileRunning(!!q.state.data?.some((r) => r.status === 'running')),
  })

export const useInjectionRun = (projectId: string | undefined, runId: string | undefined) =>
  useQuery({
    queryKey: [...qk.injection(projectId ?? ''), runId],
    queryFn: () => api.get<InjectionRun>(`${evalBase(projectId!)}/injection/${runId}`),
    enabled: !!projectId && !!runId,
    refetchInterval: (q) => pollWhileRunning(q.state.data?.status === 'running'),
  })

export const useAdapters = (projectId: string | undefined) =>
  useQuery({
    queryKey: qk.adapters(projectId ?? ''),
    queryFn: () => api.get<Adapter[]>(`${evalBase(projectId!)}/adapters`),
    enabled: !!projectId,
    refetchInterval: (q) => pollWhileRunning(!!q.state.data?.some((a) => a.status === 'running')),
  })

export function useTrainAdapter(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { set_id: string; version_id?: string }) =>
      api.post<{ adapter: Adapter; job_id: string }>(`${evalBase(projectId)}/adapters`, body),
    onSuccess: () => void qc.invalidateQueries({ queryKey: qk.adapters(projectId) }),
  })
}

export function useDeleteAdapter(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.del(`${evalBase(projectId)}/adapters/${id}`),
    onSuccess: () => void qc.invalidateQueries({ queryKey: qk.adapters(projectId) }),
  })
}

export const usePromptRuns = (projectId: string | undefined) =>
  useQuery({
    queryKey: qk.promptRuns(projectId ?? ''),
    queryFn: () => api.get<PromptRun[]>(`${evalBase(projectId!)}/prompt-runs`),
    enabled: !!projectId,
    refetchInterval: (q) => pollWhileRunning(!!q.state.data?.some((r) => r.status === 'running')),
  })

export function useStartPromptRun(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { set_id: string; version_id?: string }) =>
      api.post<{ run: PromptRun; job_id: string }>(`${evalBase(projectId)}/prompt-runs`, body),
    onSuccess: () => void qc.invalidateQueries({ queryKey: qk.promptRuns(projectId) }),
  })
}

export function useStartInjection(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { set_id: string; version_id?: string; questions: number; compare: boolean }) =>
      api.post<{ run: InjectionRun; job_id: string }>(`${evalBase(projectId)}/injection`, body),
    onSuccess: () => void qc.invalidateQueries({ queryKey: qk.injection(projectId) }),
  })
}

export function useStartSweep(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { set_id: string; version_id?: string; axes: { path: string; values: unknown[] }[]; auto_optimize?: boolean; judge?: Judge }) =>
      api.post<{ sweep: Sweep; job_id: string }>(`${evalBase(projectId)}/sweeps`, body),
    onSuccess: () => void qc.invalidateQueries({ queryKey: qk.sweeps(projectId) }),
  })
}

export function useCancelSweep(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (sweepId: string) => api.post<Sweep>(`${evalBase(projectId)}/sweeps/${sweepId}/cancel`),
    onSuccess: () => void qc.invalidateQueries({ queryKey: qk.sweeps(projectId) }),
  })
}

// ------------------------------------------------------------------------------------------ corpus health

const healthBase = (projectId: string) => `/projects/${projectId}/health`

export const useHealthReports = (projectId: string | undefined) =>
  useQuery({
    queryKey: qk.healthReports(projectId ?? ''),
    queryFn: () => api.get<HealthReport[]>(`${healthBase(projectId!)}/reports`),
    enabled: !!projectId,
    refetchInterval: (q) => pollWhileRunning(!!q.state.data?.some((r) => r.status === 'running')),
  })

export const useHealthReport = (projectId: string | undefined, reportId: string | null | undefined) =>
  useQuery({
    queryKey: qk.healthReport(projectId ?? '', reportId ?? ''),
    queryFn: () => api.get<HealthReport>(`${healthBase(projectId!)}/reports/${reportId}`),
    enabled: !!projectId && !!reportId,
    refetchInterval: (q) => pollWhileRunning(q.state.data?.status === 'running'),
  })

export const useHealthMonitor = (projectId: string) =>
  useQuery({
    queryKey: ['projects', projectId, 'health', 'monitor'],
    queryFn: () => api.get<HealthMonitor>(`${healthBase(projectId)}/monitor`),
    refetchInterval: 15_000,
  })

export function useSaveHealthMonitor(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (settings: HealthMonitor['settings']) =>
      api.put<HealthMonitor & { job_id: string | null }>(`${healthBase(projectId)}/monitor`, settings),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['projects', projectId, 'health', 'monitor'] })
      void qc.invalidateQueries({ queryKey: qk.healthReports(projectId) })
    },
  })
}

export function useStartHealthReport(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { version_id?: string; questions?: string[]; stale_days?: number; sources?: 'all' | 'api' }) =>
      api.post<{ report: HealthReport; job_id: string }>(`${healthBase(projectId)}/reports`, body),
    onSuccess: () => void qc.invalidateQueries({ queryKey: qk.healthReports(projectId) }),
  })
}

export const healthReportUrl = (projectId: string, reportId: string) =>
  buildUrl(`${healthBase(projectId)}/reports/${reportId}/report.md`)

/** One-click fixes for a ready eval run's miss diagnoses. */
export const useEvalFixes = (projectId: string, runId: string | null | undefined) =>
  useQuery({
    queryKey: qk.evalFixes(projectId, runId ?? ''),
    queryFn: () => api.get<EvalFix[]>(`${evalBase(projectId)}/runs/${runId}/fixes`),
    enabled: !!runId,
  })

// ------------------------------------------------------------------------------------------ eval-set edits

const invalidateSet = (qc: ReturnType<typeof useQueryClient>, projectId: string, setId: string) =>
  void qc.invalidateQueries({ queryKey: qk.evalSet(projectId, setId) })

export function useAddEvalItem(projectId: string, setId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { question: string; gold_answer: string; evidence: string; document_id: string; facets?: string[]; tests?: string }) =>
      api.post(`${evalBase(projectId)}/sets/${setId}/items`, body),
    onSuccess: () => invalidateSet(qc, projectId, setId),
  })
}

export function useUpdateEvalItem(projectId: string, setId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ itemId, ...body }: { itemId: string; question?: string; gold_answer?: string; evidence?: string; facets?: string[]; tests?: string; valid?: boolean }) =>
      api.patch(`${evalBase(projectId)}/sets/${setId}/items/${itemId}`, body),
    onSuccess: () => invalidateSet(qc, projectId, setId),
  })
}

export function useDeleteEvalItem(projectId: string, setId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (itemId: string) => api.del(`${evalBase(projectId)}/sets/${setId}/items/${itemId}`),
    onSuccess: () => invalidateSet(qc, projectId, setId),
  })
}

export function useImportEvalCsv(projectId: string, setId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (csv: string) =>
      api.post<{ added: number; skipped: number; error_count: number; errors: { row: number; message: string }[] }>(
        `${evalBase(projectId)}/sets/${setId}/import`, { csv }),
    onSuccess: () => invalidateSet(qc, projectId, setId),
  })
}

export const evalSetCsvUrl = (projectId: string, setId: string) => buildUrl(`${evalBase(projectId)}/sets/${setId}/export.csv`)
