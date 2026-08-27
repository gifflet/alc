// RunCost.tsx — Say how many engine turns a button is about to buy.
//
// Every launcher in this app fires on one click with no estimate, while the
// only actions that ask for confirmation are the ones that delete something.
// The app protected people from losing work and not from spending money.
//
// Explore is the sharp end: it multiplies variants × engines × tiers from an
// unbounded number field, so three engines, two tiers and five variants is
// thirty parallel runs from a single press.
import { AlertTriangle, Coins } from 'lucide-react'

/** How many engine turns a fan-out will start. */
export function runCount(variants: number, engines: number, tiers: number): number {
  // Zero selected means "the manifest default", which is one — not none.
  return Math.max(1, variants) * Math.max(1, engines) * Math.max(1, tiers)
}

export function RunCost({ count }: { count: number }) {
  if (count <= 1) return null
  // Ten is where a fan-out stops being a comparison and starts being a bill.
  const heavy = count >= 10
  return (
    <p
      className={`flex items-start gap-1.5 text-[length:var(--ui-text-label)] ${
        heavy ? 'text-warn' : 'text-faint'
      }`}
    >
      {heavy ? (
        <AlertTriangle className="mt-[1px] h-3 w-3 shrink-0" />
      ) : (
        <Coins className="mt-[1px] h-3 w-3 shrink-0" />
      )}
      This starts <span className="text-primary">&nbsp;{count} runs</span>
      {heavy ? ' — each one is a separate engine turn you pay for.' : ', one engine turn each.'}
    </p>
  )
}
