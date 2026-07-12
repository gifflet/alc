// ProjectContext.tsx — The active project id, shared across the shell + views.
import { createContext, useContext } from 'react'

const ProjectContext = createContext<string | null>(null)

export const ProjectProvider = ProjectContext.Provider

/** The active project id. Throws outside a project shell (a programming error). */
export function useProjectId(): string {
  const id = useContext(ProjectContext)
  if (!id) throw new Error('useProjectId must be used within a ProjectProvider')
  return id
}
