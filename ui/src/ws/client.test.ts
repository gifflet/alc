import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { WsClient } from './client'
import type { WebSocketLike } from './client'
import type { WsMessage } from '../api/types'

class FakeSocket implements WebSocketLike {
  sent: string[] = []
  onopen: (() => void) | null = null
  onclose: (() => void) | null = null
  onmessage: ((ev: { data: string }) => void) | null = null
  onerror: (() => void) | null = null
  closed = false

  send(data: string): void {
    this.sent.push(data)
  }
  close(): void {
    this.closed = true
    this.onclose?.()
  }
  // Test helpers
  fireOpen(): void {
    this.onopen?.()
  }
  fireMessage(msg: unknown): void {
    this.onmessage?.({ data: JSON.stringify(msg) })
  }
  fireClose(): void {
    this.onclose?.()
  }
}

let sockets: FakeSocket[]
function makeClient() {
  sockets = []
  const client = new WsClient({
    url: 'ws://x/ws',
    createSocket: () => {
      const s = new FakeSocket()
      sockets.push(s)
      return s
    },
    backoffMs: () => 10,
  })
  return client
}

beforeEach(() => {
  vi.useFakeTimers()
})
afterEach(() => {
  vi.useRealTimers()
})

describe('WsClient', () => {
  it('subscribes on open when a project is set', () => {
    const client = makeClient()
    client.setProject('p1')
    client.connect()
    expect(client.status).toBe('connecting')
    sockets[0].fireOpen()
    expect(client.status).toBe('open')
    expect(JSON.parse(sockets[0].sent[0])).toEqual({ type: 'subscribe', project_id: 'p1' })
  })

  it('resubscribes immediately when the project changes on an open socket', () => {
    const client = makeClient()
    client.connect()
    sockets[0].fireOpen()
    client.setProject('p2')
    expect(JSON.parse(sockets[0].sent.at(-1) as string)).toEqual({
      type: 'subscribe',
      project_id: 'p2',
    })
  })

  it('dispatches parsed messages to handlers', () => {
    const client = makeClient()
    const received: WsMessage[] = []
    client.on((m) => received.push(m))
    client.connect()
    sockets[0].fireOpen()
    sockets[0].fireMessage({ type: 'queue_changed', project_id: 'p1' })
    expect(received).toEqual([{ type: 'queue_changed', project_id: 'p1' }])
  })

  it('reconnects with backoff after an unexpected close and resubscribes', () => {
    const client = makeClient()
    client.setProject('p1')
    client.connect()
    sockets[0].fireOpen()
    sockets[0].fireClose()
    expect(client.status).toBe('connecting')
    vi.advanceTimersByTime(10)
    expect(sockets).toHaveLength(2)
    sockets[1].fireOpen()
    expect(JSON.parse(sockets[1].sent[0])).toEqual({ type: 'subscribe', project_id: 'p1' })
  })

  it('does not reconnect after an intentional close', () => {
    const client = makeClient()
    client.connect()
    sockets[0].fireOpen()
    client.close()
    expect(client.status).toBe('closed')
    vi.advanceTimersByTime(1000)
    expect(sockets).toHaveLength(1)
  })

  it('notifies status listeners', () => {
    const client = makeClient()
    const statuses: string[] = []
    client.onStatus((s) => statuses.push(s))
    client.connect()
    sockets[0].fireOpen()
    expect(statuses).toEqual(['connecting', 'open'])
  })
})
