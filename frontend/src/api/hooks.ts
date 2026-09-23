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
import { api } from './client'
import { subscribeJobEvents } from './sse'
import type {
  AddUrlBody,
  Build,
  ChatBody,
  ChatResult,
  ChunksResult,
  CreateProjectBody,
  CreateVersionBody,
  CreateVersionResult,
  Document,
  EstimateResult,
  Health,
  Job,
  JobDoneResult,
  JobEvent,
  JobStage,
  ModelKind,
  ModelList,
  PipelineConfig,
  Project,
  Provider,
  RunDetail,
  RunSummary,
  SlotCatalog,
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
  job: (jobId: string) => ['jobs', jobId] as const,
  run: (runId: string) => ['runs', runId] as const,
}

/** Invalidate everything under a project (project, versions, documents, builds, jobs, runs) + the list. */
export function invalidateProject(qc: QueryClient, projectId: string) {
  void qc.invalidateQueries({ queryKey: qk.project(projectId) })
  void qc.invalidateQueries({ queryKey: qk.projects, exact: true })
}

type QOpts<T> = Omit<UseQueryOptions<T, Error, T, readonly unknown[]>, 'queryKey' | 'queryFn'>

const isBusy = (s?: string) => s === 'building' || s === 'pending'

// ------------------------------------------------------------------------------------------ system

export const useHealth = (o?: QOpts<Health>) =>
  useQuery({ queryKey: qk.health, queryFn: () => api.get<Health>('/health'), staleTime: 60_000, ...o })

export const useProviders = (o?: QOpts<Provider[]>) =>
  useQuery({ queryKey: qk.providers, queryFn: () => api.get<Provider[]>('/providers'), staleTime: 60_000, ...o })

/** True when no LLM provider key is configured (show the warning banner). undefined while loading. */
export function useNoProviderKey(): boolean | undefined {
  const { data } = useProviders()
  return data ? !data.some((p) => p.available) : undefined
}

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

export const useBuilds = (projectId: string | undefined, o?: QOpts<Build[]>) =>
  useQuery({
    queryKey: qk.builds(projectId ?? ''),
    queryFn: () => api.get<Build[]>(`/projects/${projectId}/builds`),
    enabled: !!projectId,
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

/** Creates a NEW version copying `vid`. */
export function useRollbackVersion(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (vid: string) => api.post<VersionJobResult>(`/projects/${projectId}/versions/${vid}/rollback`),
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

export function useUploadDocuments(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ files, build = true }: { files: File[] | FileList; build?: boolean }) => {
      const fd = new FormData()
      for (const f of Array.from(files)) fd.append('files', f, f.name)
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

export const useJob = (jobId: string | null | undefined, o?: QOpts<Job>) =>
  useQuery({
    queryKey: qk.job(jobId ?? ''),
    queryFn: () => api.get<Job>(`/jobs/${jobId}`),
    enabled: !!jobId,
    retry: false,
    ...o,
  })

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

export const useRuns = (projectId: string | undefined, limit = 50, o?: QOpts<RunSummary[]>) =>
  useQuery({
    queryKey: qk.runs(projectId ?? '', limit),
    queryFn: () => api.get<RunSummary[]>(`/projects/${projectId}/runs`, { limit }),
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
