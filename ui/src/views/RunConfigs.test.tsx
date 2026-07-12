import { beforeEach, describe, expect, it } from 'vitest'
import { fireEvent, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { RunConfigs } from './RunConfigs'
import { RunConfigForm } from './RunConfigForm'
import { execStore } from '../app/execStore'
import { uiStore } from '../app/uiStore'
import { installFetch, renderWithProviders, res } from '../test/utils'
import type { FetchCall } from '../test/utils'
import type { CommandSchema, RunConfig } from '../api/types'

const schema: CommandSchema = {
  run: {
    positionals: ['blueprint', 'task'],
    opt_positionals: [],
    value_flags: ['engine', 'tier'],
    bool_flags: ['isolate'],
  },
  lint: { positionals: [], opt_positionals: [], value_flags: [], bool_flags: ['json'] },
}

const engines = [
  { name: 'mock', type: 'mock', default: true, tiers: { standard: 'mock-small' }, healthy: true },
]

const shipConfig: RunConfig = {
  name: 'ship chore',
  command: 'run',
  args: { blueprint: 'chore', task: 'tidy', isolate: true },
}

beforeEach(() => {
  localStorage.clear()
  uiStore.reset()
  execStore.reset()
})

describe('RunConfigForm', () => {
  it('generates fields from the command schema and creates a config', async () => {
    const mock = installFetch({
      '/api/commands': schema,
      '/engines': engines,
      '/run-configs': { name: 'ship chore', command: 'run', args: {} },
    })
    renderWithProviders(<RunConfigForm onClose={() => {}} />)

    // Fields are generated from the `run` spec: positionals, value flags, bool flag.
    fireEvent.change(await screen.findByLabelText('Name'), { target: { value: 'ship chore' } })
    fireEvent.change(await screen.findByLabelText('blueprint'), { target: { value: 'chore' } })
    fireEvent.change(screen.getByLabelText('task'), { target: { value: 'tidy' } })
    expect(screen.getByLabelText('engine')).toBeInTheDocument()
    expect(screen.getByLabelText('tier')).toBeInTheDocument()
    await userEvent.click(screen.getByLabelText('isolate'))
    await userEvent.click(screen.getByRole('button', { name: 'Create' }))

    const post = mock.calls.find((c) => c.method === 'POST' && c.url.includes('/run-configs'))
    expect(post?.body).toEqual({
      name: 'ship chore',
      command: 'run',
      args: { blueprint: 'chore', task: 'tidy', isolate: true },
    })
  })

  it('updates an existing config through PUT', async () => {
    const mock = installFetch({
      '/api/commands': schema,
      '/engines': engines,
      '/run-configs': { name: 'ship chore', command: 'run', args: {} },
    })
    renderWithProviders(<RunConfigForm existing={shipConfig} onClose={() => {}} />)

    fireEvent.change(await screen.findByLabelText('task'), { target: { value: 'tidy up' } })
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))

    const put = mock.calls.find((c) => c.method === 'PUT')
    expect(put?.url).toContain('/run-configs/ship%20chore')
    expect(put?.body).toEqual({
      name: 'ship chore',
      command: 'run',
      args: { blueprint: 'chore', task: 'tidy up', isolate: true },
    })
  })
})

describe('RunConfigs', () => {
  it('runs a config, dispatching useStartExec and registering the exec', async () => {
    const mock = installFetch({
      '/api/commands': schema,
      '/engines': engines,
      '/run-configs': { configs: [shipConfig] },
      '/exec': { exec_id: 'e1' },
    })
    renderWithProviders(<RunConfigs />)

    await userEvent.click(await screen.findByRole('button', { name: 'Run ship chore' }))

    const post = mock.calls.find((c) => c.method === 'POST' && c.url.includes('/exec'))
    expect(post?.body).toEqual({
      command: 'run',
      args: { blueprint: 'chore', task: 'tidy', isolate: true },
    })
    expect(execStore.getState().execs[0]?.id).toBe('e1')
    expect(execStore.getState().execs[0]?.command).toBe('run')
  })

  it('runs the config picked in the header selector', async () => {
    const mock = installFetch({
      '/api/commands': schema,
      '/engines': engines,
      '/run-configs': { configs: [shipConfig] },
      '/exec': { exec_id: 'e2' },
    })
    renderWithProviders(<RunConfigs />)

    fireEvent.change(await screen.findByLabelText('Run configuration'), {
      target: { value: 'ship chore' },
    })
    await userEvent.click(screen.getByRole('button', { name: 'Run selected configuration' }))

    const post = mock.calls.find((c) => c.method === 'POST' && c.url.includes('/exec'))
    expect(post?.body).toEqual({
      command: 'run',
      args: { blueprint: 'chore', task: 'tidy', isolate: true },
    })
  })

  it('deletes a config after confirmation', async () => {
    const mock = installFetch({
      '/api/commands': schema,
      '/engines': engines,
      '/run-configs': (call: FetchCall) =>
        call.method === 'DELETE' ? res(204, {}) : { configs: [shipConfig] },
    })
    renderWithProviders(<RunConfigs />)

    await userEvent.click(await screen.findByRole('button', { name: 'Delete ship chore' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Delete' }))

    const del = mock.calls.find((c) => c.method === 'DELETE')
    expect(del?.url).toContain('/run-configs/ship%20chore')
  })
})
