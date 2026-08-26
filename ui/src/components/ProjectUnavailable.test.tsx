import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ProjectUnavailable } from './ProjectUnavailable'

describe('ProjectUnavailable', () => {
  it('names the id and reassures about the files when unregistered', () => {
    render(
      <ProjectUnavailable id="ghost-1a2b" reason="unregistered" onOpenProjects={() => {}} />,
    )
    expect(screen.getByText('Project not registered')).toBeInTheDocument()
    expect(screen.getByText('ghost-1a2b')).toBeInTheDocument()
    // Removing a project from the control room does not delete anything.
    expect(screen.getByText(/files on disk are untouched/)).toBeInTheDocument()
  })

  it('names the manifest and the path when the folder is gone', () => {
    render(
      <ProjectUnavailable
        id="proj-1a2b"
        name="proj"
        path="/tmp/proj"
        reason="missing"
        onOpenProjects={() => {}}
      />,
    )
    expect(screen.getByText('Project unavailable')).toBeInTheDocument()
    expect(screen.getByText('.alc/manifest.yaml')).toBeInTheDocument()
    expect(screen.getByText('/tmp/proj')).toBeInTheDocument()
  })

  it('distinguishes the two causes rather than showing one generic error', () => {
    const { unmount } = render(
      <ProjectUnavailable id="x" reason="unregistered" onOpenProjects={() => {}} />,
    )
    const first = screen.getByRole('heading').textContent
    unmount()
    render(<ProjectUnavailable id="x" reason="missing" onOpenProjects={() => {}} />)
    expect(screen.getByRole('heading').textContent).not.toBe(first)
  })

  it('offers the one action that resolves it', async () => {
    const onOpenProjects = vi.fn()
    render(<ProjectUnavailable id="x" reason="unregistered" onOpenProjects={onOpenProjects} />)
    await userEvent.click(screen.getByRole('button', { name: 'Open projects' }))
    expect(onOpenProjects).toHaveBeenCalledOnce()
  })
})
