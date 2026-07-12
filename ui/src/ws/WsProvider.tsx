// WsProvider.tsx — Own the WsClient lifecycle and bridge it into the app.
//
// - Subscribes the socket to the active project.
// - Turns every message into TanStack Query invalidations (live views, no refresh).
// - Exposes the client (for direct run/console subscriptions) and WS status.
import { createContext, useContext, useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { keys } from '../api/keys'
import { WsClient } from './client'
import type { WsStatus } from './client'
import { wsInvalidations } from './invalidate'

function wsUrl(): string {
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${window.location.host}/ws`
}

interface WsContextValue {
  client: WsClient
  status: WsStatus
}

const WsContext = createContext<WsContextValue | null>(null)

export function WsProvider({
  projectId,
  children,
}: {
  projectId: string | null
  children: ReactNode
}) {
  const queryClient = useQueryClient()
  const clientRef = useRef<WsClient | null>(null)
  if (clientRef.current === null) {
    clientRef.current = new WsClient({ url: wsUrl() })
  }
  const client = clientRef.current
  const [status, setStatus] = useState<WsStatus>(client.status)

  useEffect(() => {
    const offStatus = client.onStatus((s) => {
      setStatus(s)
      // Re-probe engine health whenever the link (re)opens — a dropped socket
      // often means the backend or an engine bounced.
      if (s === 'open' && projectId) {
        queryClient.invalidateQueries({ queryKey: keys.engines(projectId) })
      }
    })
    const offMsg = client.on((msg) => {
      for (const key of wsInvalidations(msg)) {
        queryClient.invalidateQueries({ queryKey: key })
      }
    })
    client.connect()
    return () => {
      offStatus()
      offMsg()
      client.close()
    }
  }, [client, queryClient, projectId])

  useEffect(() => {
    client.setProject(projectId)
  }, [client, projectId])

  const value = useMemo<WsContextValue>(() => ({ client, status }), [client, status])
  return <WsContext.Provider value={value}>{children}</WsContext.Provider>
}

export function useWs(): WsContextValue {
  const ctx = useContext(WsContext)
  if (!ctx) throw new Error('useWs must be used within a WsProvider')
  return ctx
}
