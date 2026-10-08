/* oxlint-disable react/only-export-components -- route table module, not hot-reloaded components */
import { lazy } from 'react'
import { Navigate, createBrowserRouter, useRouteError } from 'react-router-dom'
import { SearchX, TriangleAlert } from 'lucide-react'
import { errorMessage } from '@/api/client'
import { ButtonLink, EmptyState } from '@/components/ui'
import { AppLayout } from './AppLayout'
import { WorkspaceLayout } from './WorkspaceLayout'

const ProjectsPage = lazy(() => import('@/features/projects/ProjectsPage'))
const CreateWizard = lazy(() => import('@/features/wizard/CreateWizard'))
const DocumentsTab = lazy(() => import('@/features/documents/DocumentsTab'))
const DataTab = lazy(() => import('@/features/data/DataTab'))
const RecipesPage = lazy(() => import('@/features/recipes/RecipesPage'))
const ConfigureTab = lazy(() => import('@/features/configure/ConfigureTab'))
const VersionsTab = lazy(() => import('@/features/versions/VersionsTab'))
const PlaygroundTab = lazy(() => import('@/features/playground/PlaygroundTab'))
const ApiTab = lazy(() => import('@/features/api/ApiTab'))
const EvaluateTab = lazy(() => import('@/features/evaluate/EvaluateTab'))
const HealthTab = lazy(() => import('@/features/health/HealthTab'))
const ProvidersPage = lazy(() => import('@/features/settings/ProvidersPage'))

function NotFound() {
  return (
    <div className="px-4 py-12 sm:px-8">
      <EmptyState
        icon={<SearchX aria-hidden />}
        title="Page not found"
        description="That address doesn't match any page."
        actions={<ButtonLink to="/" variant="primary">All projects</ButtonLink>}
      />
    </div>
  )
}

function RouteError() {
  const err = useRouteError()
  return (
    <div className="px-4 py-12 sm:px-8">
      <EmptyState
        icon={<TriangleAlert aria-hidden />}
        title="Something went wrong"
        description={errorMessage(err)}
        actions={<ButtonLink to="/" variant="primary">All projects</ButtonLink>}
      />
    </div>
  )
}

export const router = createBrowserRouter([
  {
    element: <AppLayout />,
    errorElement: <RouteError />,
    children: [
      { index: true, element: <ProjectsPage /> },
      { path: 'new', element: <CreateWizard /> },
      { path: 'projects/new', element: <Navigate to="/new" replace /> },
      { path: 'settings/providers', element: <ProvidersPage /> },
      { path: 'recipes', element: <RecipesPage /> },
      {
        path: 'projects/:id',
        element: <WorkspaceLayout />,
        errorElement: <RouteError />,
        children: [
          { index: true, element: <Navigate to="documents" replace /> },
          { path: 'documents', element: <DocumentsTab /> },
          { path: 'data', element: <DataTab /> },
          { path: 'configure', element: <ConfigureTab /> },
          { path: 'versions', element: <VersionsTab /> },
          { path: 'playground', element: <PlaygroundTab /> },
          { path: 'evaluate', element: <EvaluateTab /> },
          { path: 'health', element: <HealthTab /> },
          { path: 'api', element: <ApiTab /> },
        ],
      },
      { path: '*', element: <NotFound /> },
    ],
  },
])
