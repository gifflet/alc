// ShortcutsDialog.tsx — The "Keyboard shortcuts" reference panel (opened by ?).
import { Dialog } from './Dialog'

/** Cmd on Apple platforms, Ctrl elsewhere — matches useShortcuts (mod key). */
const MOD = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform) ? '⌘' : 'Ctrl'

const SHORTCUTS: [string, string][] = [
  [
    `${MOD} 1 – 9`,
    'Dashboard / Queue / Runs / Loops / Conduct / Team / Metrics / Compare / Checks',
  ],
  [`${MOD} W`, 'Close the active tab'],
  [`${MOD} S`, 'Save the open editor'],
  [`${MOD} J`, 'Toggle the bottom panel'],
  [`${MOD} B`, 'Toggle the project tool window'],
  ['?', 'Show this shortcuts panel'],
]

function Kbd({ children }: { children: string }) {
  return (
    <kbd className="rounded-panel border border-border bg-base px-1.5 py-0.5 font-mono text-[11px] text-primary">
      {children}
    </kbd>
  )
}

export function ShortcutsDialog({ onClose }: { onClose: () => void }) {
  return (
    <Dialog title="Keyboard shortcuts" onClose={onClose} width={420}>
      <ul className="flex flex-col gap-1.5">
        {SHORTCUTS.map(([keys, label]) => (
          <li key={keys} className="flex items-center justify-between gap-4 text-[12px]">
            <span className="text-muted">{label}</span>
            <Kbd>{keys}</Kbd>
          </li>
        ))}
      </ul>
    </Dialog>
  )
}
