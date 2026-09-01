// App.tsx — Providers + routing. Project scope lives in the URL (/projects/:id);
// everything inside a project is driven by the tab store, not the router.
import { useEffect, useState } from 'react'
import { QueryCache, QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Navigate, Route, Routes, useNavigate, useParams } from 'react-router'
import { Boxes } from 'lucide-react'
import { useProjects } from '../api/hooks'
import { ProjectProvider } from './ProjectContext'
import { WsProvider } from '../ws/WsProvider'
import { Shell } from './Shell'
import { UrlSync, useUrlHydration } from './urlSync'
import { useApplyDensity } from './useDensity'
import { useApplyTheme } from './useTheme'
import { authStore, useUnauthorized } from './authStore'
import { ApiError } from '../api/client'
import { TokenPrompt } from '../components/TokenPrompt'
import { ProjectSelector } from '../components/ProjectSelector'
import { ProjectSwitcher } from '../components/ProjectSwitcher'
import { EmptyState } from '../components/EmptyState'
import { ProjectUnavailable } from '../components/ProjectUnavailable'

/** Module-scoped so the cache survives navigation; exported so tests can
 * clear it between cases (otherwise one test's projects leak into the next). */
export const queryClient = new QueryClient({
  // A 401 is caught globally: otherwise every query fails empty and each view
  // renders its "nothing here" state, which would make the control room report
  // an idle project while units are actually running.
  queryCache: new QueryCache({
    onError: (error) => {
      if (error instanceof ApiError && error.status === 401) authStore.setUnauthorized(true)
    },
  }),
  defaultOptions: {
    queries: { staleTime: 5_000, refetchOnWindowFocus: false, retry: 1 },
  },
})

function Landing() {
  const { data: projects, isLoading } = useProjects()
  const navigate = useNavigate()
  const [open, setOpen] = useState(true)

  useEffect(() => {
    // Forward past the landing only when the choice is not a choice: exactly
    // one project. With several, `/` used to drop a newcomer inside whichever
    // project happened to be registered first — someone else's dashboard as a
    // front door (dogfood finding 21). The selector is already on screen.
    if (projects?.length === 1) {
      navigate(`/projects/${projects[0].id}`, { replace: true })
    }
  }, [projects, navigate])

  if (isLoading) return <EmptyState icon={Boxes} message="Loading projects…" />
  return (
    // ProjectSelector needs the socket: cloning a repo and creating a project
    // report progress over it, as global execs with no project attached. There
    // is no project here yet, which is exactly what `projectId={null}` is for —
    // the client subscribes to the global bus and nothing else.
    <WsProvider projectId={null}>
      <div className="h-full">
        <EmptyState icon={Boxes} message="No project open. Register one to begin." />
        {open && (
          <ProjectSelector
            activeId={null}
            onClose={() => setOpen(false)}
            onSelect={(id) => navigate(`/projects/${id}`)}
          />
        )}
      </div>
    </WsProvider>
  )
}

function ProjectShell() {
  const { id = '' } = useParams()
  const navigate = useNavigate()
  const { data: projects, isLoading } = useProjects()
  const [selectorOpen, setSelectorOpen] = useState(false)
  const [switcherOpen, setSwitcherOpen] = useState(false)

  // Reset + hydrate the tab store from the URL once per project; `hydrated` gates
  // UrlSync so the two-way binding can never turn into a navigation loop.
  // Called before any early return so the hook order never changes.
  const hydrated = useUrlHydration(id)

  const project = projects?.find((p) => p.id === id)
  const projectName = project?.name ?? id

  // The shell addresses ONE project. When that project cannot be reached, the
  // shell is not rendered: a rail of enabled buttons and a cached file tree
  // would describe a project the backend answers 404/410 for.
  const unavailable = !isLoading && (!project || !project.available)

  // Until the list arrives we know nothing — and rendering the shell meanwhile
  // would fire every project-scoped query against an id that may not exist, then
  // swap it out. Say "loading", which is the only true statement here.
  if (isLoading) return <EmptyState icon={Boxes} message="Loading project…" />

  if (unavailable) {
    return (
      <>
        <ProjectUnavailable
          id={id}
          name={project?.name}
          path={project?.path}
          reason={project ? 'missing' : 'unregistered'}
          onOpenProjects={() => setSelectorOpen(true)}
        />
        {selectorOpen && (
          <WsProvider projectId={null}>
            <ProjectSelector
              activeId={null}
              onClose={() => setSelectorOpen(false)}
              onSelect={(next) => {
                setSelectorOpen(false)
                navigate(`/projects/${next}`)
              }}
            />
          </WsProvider>
        )}
      </>
    )
  }

  return (
    <ProjectProvider value={id}>
      <WsProvider projectId={id}>
        <UrlSync id={id} hydrated={hydrated} />
        <Shell
          projectName={projectName}
          onOpenProjects={() => setSelectorOpen(true)}
          onSwitchProject={() => setSwitcherOpen(true)}
        />
        {switcherOpen && (
          <ProjectSwitcher
            projects={projects ?? []}
            activeId={id}
            onClose={() => setSwitcherOpen(false)}
            onSelect={(next) => {
              setSwitcherOpen(false)
              if (next !== id) navigate(`/projects/${next}`)
            }}
            // Registering is a different job; the switcher hands off to the
            // panel that owns it rather than growing a form inside itself.
            onRegister={() => {
              setSwitcherOpen(false)
              setSelectorOpen(true)
            }}
          />
        )}
        {selectorOpen && (
          <ProjectSelector
            activeId={id}
            onClose={() => setSelectorOpen(false)}
            onSelect={(next) => {
              setSelectorOpen(false)
              if (next !== id) navigate(`/projects/${next}`)
            }}
          />
        )}
      </WsProvider>
    </ProjectProvider>
  )
}

export function Authenticated() {
  // Replaces the whole app: with no credential there is no project state to
  // show, and a view's empty state would misreport the project.
  if (useUnauthorized()) return <TokenPrompt />
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/projects/:id/*" element={<ProjectShell />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}

export function App() {
  // Density is a property of the document, resolved once at the root: every
  // component then reads CSS custom properties instead of querying the viewport.
  useApplyDensity()
  useApplyTheme()
  return (
    <QueryClientProvider client={queryClient}>
      <Authenticated />
    </QueryClientProvider>
  )
}
