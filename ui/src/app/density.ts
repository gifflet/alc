// density.ts — Pure resolution of the UI density mode.
//
// Resolution is separate from the DOM plumbing (useDensity owns that), so the
// rule is unit-tested without a browser — the same split shortcuts.ts uses.
//
// `compact` is today's desktop, byte-for-byte. `comfortable` lifts every target
// to the 44px touch floor.

export type Density = 'compact' | 'cozy' | 'comfortable'

/** Touch-first pointer — a phone or tablet, regardless of viewport width. */
export const COARSE_QUERY = '(pointer: coarse)'
/** The narrow breakpoint: below it the IDE grid does not apply. */
export const NARROW_QUERY = '(max-width: 767px)'
/** A touch screen this wide is a laptop with a touchscreen, not a tablet: the
 * operator is at a keyboard and a mouse, so density should not balloon. */
export const WIDE_QUERY = '(min-width: 1280px)'

/**
 * The density to apply.
 *
 * Three contexts, not two. The old rule (`coarse || narrow -> comfortable`) put
 * a tablet in phone density inside the desktop IDE grid — a combination nobody
 * designed, measured on an emulated iPad. And it demoted a touchscreen LAPTOP
 * to phone density even though its operator sits at a keyboard.
 *
 *   phone   (narrow)                  -> comfortable  (44px targets)
 *   tablet  (touch, 768-1279px)       -> cozy         (40px targets, 14px type)
 *   laptop  (touch but >= 1280px)     -> compact      (a mouse is in play)
 *   desktop (fine pointer)            -> compact
 *
 * An explicit operator override always wins — someone with poor eyesight may
 * want the roomy scale on a desktop, and that is their call, not ours.
 */
export function resolveDensity(
  override: Density | null,
  coarsePointer: boolean,
  narrowViewport: boolean,
  wideViewport = false,
): Density {
  if (override) return override
  if (narrowViewport) return 'comfortable'
  if (coarsePointer && !wideViewport) return 'cozy'
  return 'compact'
}
