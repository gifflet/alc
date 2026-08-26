import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ProjectSwitcher, filterProjects } from './ProjectSwitcher'
import type { ProjectSummary } from '../api/types'

const project = (over: Partial<ProjectSummary>): ProjectSummary => ({
  id: 'p1',
  name: 'alpha',
  path: '/home/dev/alpha',
  available: true,
  default_engine: 'mock',
  queue_pending: 0,
  ...over,
})

const PROJECTS = [
  project({ id: 'p1', name: 'alpha', path: '/home/dev/alpha' }),
  project({ id: 'p2', name: 'beta', path: '/srv/work/beta' }),
  project({ id: 'p3', name: 'gone', path: '/tmp/gone', available: false }),
]

describe('filterProjects', () => {
  it('matches on name and on path', () => {
    expect(filterProjects(PROJECTS, 'beta').map((p) => p.id)).toEqual(['p2'])
    expect(filterProjects(PROJECTS, '/srv').map((p) => p.id)).toEqual(['p2'])
  })

  it('is case-insensitive and returns everything for an empty query', () => {
    expect(filterProjects(PROJECTS, 'ALPHA').map((p) => p.id)).toEqual(['p1'])
    expect(filterProjects(PROJECTS, '   ')).toHaveLength(3)
  })
})

describe('ProjectSwitcher', () => {
  const setup = (over: Partial<Parameters<typeof ProjectSwitcher>[0]> = {}) => {
    const onSelect = vi.fn()
    const onRegister = vi.fn()
    const onClose = vi.fn()
    render(
      <ProjectSwitcher
        projects={PROJECTS}
        activeId="p1"
        onSelect={onSelect}
        onRegister={onRegister}
        onClose={onClose}
        {...over}
      />,
    )
    return { onSelect, onRegister, onClose }
  }

  it('lists every project, including one that is unavailable', () => {
    setup()
    expect(screen.getByText('alpha')).toBeInTheDocument()
    expect(screen.getByText('beta')).toBeInTheDocument()
    // A project whose directory moved stays listed and says so — hiding it would
    // report that it was never registered.
    expect(screen.getByText('gone')).toBeInTheDocument()
    expect(screen.getByText('unavailable')).toBeInTheDocument()
  })

  it('marks the active project', () => {
    setup()
    expect(screen.getByText('current')).toBeInTheDocument()
  })

  it('filters as you type and opens the match on Enter', () => {
    const { onSelect } = setup()
    const input = screen.getByLabelText('Search projects')
    fireEvent.change(input, { target: { value: 'beta' } })
    expect(screen.queryByText('alpha')).not.toBeInTheDocument()
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(onSelect).toHaveBeenCalledWith('p2')
  })

  it('says so when nothing matches, and still offers to register', () => {
    const { onRegister } = setup()
    fireEvent.change(screen.getByLabelText('Search projects'), { target: { value: 'zzz' } })
    expect(screen.getByText(/No project matches/)).toBeInTheDocument()
    fireEvent.click(screen.getByText('Register a project…'))
    expect(onRegister).toHaveBeenCalled()
  })

  it('arrows past the last project onto the register row', () => {
    const { onRegister } = setup()
    const input = screen.getByLabelText('Search projects')
    // 3 projects + the register row: four downs returns to the top, three lands
    // on register.
    fireEvent.keyDown(input, { key: 'ArrowDown' })
    fireEvent.keyDown(input, { key: 'ArrowDown' })
    fireEvent.keyDown(input, { key: 'ArrowDown' })
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(onRegister).toHaveBeenCalled()
  })

  it('closes on Escape', () => {
    const { onClose } = setup()
    fireEvent.keyDown(screen.getByLabelText('Search projects'), { key: 'Escape' })
    expect(onClose).toHaveBeenCalled()
  })
})
