// useStartExec.ts — Launch an `alc` exec for the active project.
//
// Opens the console panel, POSTs the whitelisted command, then registers the
// returned exec id in the store (live output streams in via ExecBridge). The
// caller decides how to surface a rejected promise (dialogs show the message).
import { useCallback } from 'react'
import { api } from '../api/client'
import { useProjectId } from './ProjectContext'
import { execStore } from './execStore'
import { uiStore } from './uiStore'

export function useStartExec(): (command: string, args: Record<string, unknown>) => Promise<string> {
  const projectId = useProjectId()
  return useCallback(
    async (command: string, args: Record<string, unknown>) => {
      uiStore.setBottomTab('console')
      const { exec_id } = await api.startExec(projectId, command, args)
      execStore.launch({ id: exec_id, projectId, command })
      return exec_id
    },
    [projectId],
  )
}
