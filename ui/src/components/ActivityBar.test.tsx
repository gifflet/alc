import { beforeEach, describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ActivityBar } from './ActivityBar'
import { uiStore } from '../app/uiStore'

beforeEach(() => {
  uiStore.reset()
})

describe('ActivityBar', () => {
  it('calls onOpenSpike when the Spike rail button is clicked', async () => {
    let opened = false
    render(<ActivityBar onOpenProjects={() => {}} onOpenSpike={() => (opened = true)} />)

    await userEvent.click(screen.getByLabelText('Spike'))

    expect(opened).toBe(true)
  })
})
