// ExecBridge.tsx — Feed the exec store from the WebSocket + seed from the API.
//
// Headless: subscribes the live socket to exec_output / exec_finished / run_event
// and mirrors them into execStore, and (re)seeds from GET /api/execs on mount,
// project change, and reconnect so in-flight execs recover after a drop.
import { useEffect } from 'react'
import { api } from '../api/client'
import { useProjectId } from './ProjectContext'
import { execStore } from './execStore'
import { useWs } from '../ws/WsProvider'

// Run lifecycle starts that mark a fresh run appearing in .alc/runs/.
const RUN_STARTS = new Set(['mandate_started', 'flow_started', 'task_started'])

export function ExecBridge() {
  const projectId = useProjectId()
  const { client } = useWs()

  useEffect(() => {
    const seed = () =>
      api
        .listExecs()
        .then((execs) => execStore.seed(execs))
        .catch(() => {})
    seed()

    const offMsg = client.on((msg) => {
      if (msg.type === 'exec_output') {
        execStore.output({ execId: msg.exec_id, projectId: msg.project_id, line: msg.line })
      } else if (msg.type === 'exec_finished') {
        execStore.finished({ execId: msg.exec_id, exitCode: msg.exit_code })
      } else if (msg.type === 'run_event' && RUN_STARTS.has(msg.event.event)) {
        execStore.noteRun(msg.project_id, msg.stem)
      }
    })
    const offStatus = client.onStatus((s) => {
      if (s === 'open') seed()
    })
    return () => {
      offMsg()
      offStatus()
    }
  }, [client, projectId])

  return null
}
