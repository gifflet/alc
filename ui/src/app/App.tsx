// App.tsx — Providers + routing. Project scope lives in the URL (/projects/:id);
// everything inside a project is driven by the tab store, not the router.
import { useEffect, useState } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Navigate, Route, Routes, useNavigate, useParams } from 'react-router'
import { Boxes } from 'lucide-react'
import { useProjects } from '../api/hooks'
import { ProjectProvider } from './ProjectContext'
import { WsProvider } from '../ws/WsProvider'
import { Shell } from './Shell'
import { openView } from '../components/ActivityBar'
import { uiStore } from './uiStore'
import { ProjectSelector } from '../components/ProjectSelector'
import { EmptyState } from '../components/EmptyState'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 5_000, refetchOnWindowFocus: false, retry: 1 },
  },
})

function Landing() {
  const { data: projects, isLoading } = useProjects()
  const navigate = useNavigate()
  const [open, setOpen] = useState(true)

  useEffect(() => {
    const first = projects?.find((p) => p.available) ?? projects?.[0]
    if (first) navigate(`/projects/${first.id}`, { replace: true })
  }, [projects, navigate])

  if (isLoading) return <EmptyState icon={Boxes} message="Loading projects…" />
  return (
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
  )
}

function ProjectShell() {
  const { id = '' } = useParams()
  const navigate = useNavigate()
  const { data: projects } = useProjects()
  const [selectorOpen, setSelectorOpen] = useState(false)

  // Reset tabs and land on the dashboard whenever the active project changes.
  useEffect(() => {
    uiStore.reset()
    openView('dashboard')
  }, [id])

  const project = projects?.find((p) => p.id === id)
  const projectName = project?.name ?? id

  return (
    <ProjectProvider value={id}>
      <WsProvider projectId={id}>
        <Shell projectName={projectName} onOpenProjects={() => setSelectorOpen(true)} />
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

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/projects/:id" element={<ProjectShell />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
