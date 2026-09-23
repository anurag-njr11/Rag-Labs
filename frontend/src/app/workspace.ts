import { useOutletContext, useParams } from 'react-router-dom'
import type { Project } from '@/api/types'

export interface WorkspaceContext {
  /** The loaded project (always defined inside workspace tabs; kept fresh by React Query). */
  project: Project
}

/** Inside a workspace tab: the current project, loaded by WorkspaceLayout. */
export function useWorkspace(): WorkspaceContext {
  return useOutletContext<WorkspaceContext>()
}

/** The `:id` route param (project id). */
export function useProjectId(): string {
  return useParams<{ id: string }>().id ?? ''
}

/** Workspace routes, for links: `projectPath(id, 'configure')`. */
export type WorkspaceTab = 'documents' | 'configure' | 'versions' | 'playground' | 'api'
export const projectPath = (id: string, tab: WorkspaceTab = 'documents') => `/projects/${id}/${tab}`
