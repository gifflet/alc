// Shell.tsx — Pick the layout for this screen.
//
// Two layouts, one route table: the IDE grid on a desktop, the Operator layout
// on a phone. The same URL renders in both, so a link opened on the phone shows
// exactly what it shows on the desk (tabRoute/urlSync own the URL in both).
import { IdeShell } from './IdeShell'
import { OperatorShell } from './OperatorShell'
import { useNarrow } from './useDensity'

export function Shell({
  projectName,
  onOpenProjects,
}: {
  projectName: string
  onOpenProjects: () => void
}) {
  const narrow = useNarrow()
  const Layout = narrow ? OperatorShell : IdeShell
  return <Layout projectName={projectName} onOpenProjects={onOpenProjects} />
}
