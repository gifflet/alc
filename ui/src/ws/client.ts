// client.ts — Resilient WebSocket client for /ws.
//
// Responsibilities: connect, (re)subscribe to the active project, reconnect
// with capped backoff, and fan parsed messages out to handlers. It knows
// nothing about React or TanStack Query — WsProvider wires those in.
import type { WsMessage } from '../api/types'

export type WsStatus = 'connecting' | 'open' | 'closed'

/** The subset of WebSocket the client uses (injectable for tests). */
export interface WebSocketLike {
  send(data: string): void
  close(): void
  onopen: (() => void) | null
  onclose: (() => void) | null
  onmessage: ((ev: { data: string }) => void) | null
  onerror: (() => void) | null
}

export interface WsClientOptions {
  url: string
  createSocket?: (url: string) => WebSocketLike
  /** Backoff in ms for the nth consecutive reconnect attempt (0-based). */
  backoffMs?: (attempt: number) => number
}

function defaultBackoff(attempt: number): number {
  return Math.min(500 * 2 ** attempt, 8000)
}

export class WsClient {
  private readonly url: string
  private readonly createSocket: (url: string) => WebSocketLike
  private readonly backoffMs: (attempt: number) => number

  private socket: WebSocketLike | null = null
  private projectId: string | null = null
  private closedByUser = false
  private attempt = 0
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null

  private _status: WsStatus = 'closed'
  private readonly handlers = new Set<(m: WsMessage) => void>()
  private readonly statusHandlers = new Set<(s: WsStatus) => void>()

  constructor(opts: WsClientOptions) {
    this.url = opts.url
    this.createSocket = opts.createSocket ?? ((u) => new WebSocket(u) as unknown as WebSocketLike)
    this.backoffMs = opts.backoffMs ?? defaultBackoff
  }

  get status(): WsStatus {
    return this._status
  }

  private setStatus(status: WsStatus): void {
    if (this._status === status) return
    this._status = status
    this.statusHandlers.forEach((h) => h(status))
  }

  connect(): void {
    this.closedByUser = false
    this.open()
  }

  private open(): void {
    this.setStatus('connecting')
    const socket = this.createSocket(this.url)
    this.socket = socket
    socket.onopen = () => {
      this.attempt = 0
      this.setStatus('open')
      this.sendSubscribe()
    }
    socket.onmessage = (ev) => this.dispatch(ev.data)
    socket.onclose = () => this.handleClose()
    socket.onerror = () => {
      // A socket error is always followed by a close event; let that drive reconnect.
    }
  }

  private handleClose(): void {
    this.socket = null
    if (this.closedByUser) {
      this.setStatus('closed')
      return
    }
    this.setStatus('connecting')
    const delay = this.backoffMs(this.attempt)
    this.attempt += 1
    this.reconnectTimer = setTimeout(() => this.open(), delay)
  }

  private dispatch(data: string): void {
    let message: WsMessage
    try {
      message = JSON.parse(data) as WsMessage
    } catch {
      return
    }
    this.handlers.forEach((h) => h(message))
  }

  private sendSubscribe(): void {
    if (this.socket && this.projectId) {
      this.socket.send(JSON.stringify({ type: 'subscribe', project_id: this.projectId }))
    }
  }

  /** Set the active project; resubscribes immediately when already connected. */
  setProject(projectId: string | null): void {
    this.projectId = projectId
    if (this._status === 'open') this.sendSubscribe()
  }

  on(handler: (m: WsMessage) => void): () => void {
    this.handlers.add(handler)
    return () => this.handlers.delete(handler)
  }

  onStatus(handler: (s: WsStatus) => void): () => void {
    this.statusHandlers.add(handler)
    return () => this.statusHandlers.delete(handler)
  }

  close(): void {
    this.closedByUser = true
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    this.socket?.close()
    this.socket = null
    this.setStatus('closed')
  }
}
