import { useEffect, useId, useRef, useState, type CSSProperties } from 'react'
import { createPortal } from 'react-dom'

interface InfoTipProps {
  /** What the button is about, read by screen readers, e.g. "Why Email is Contact info". */
  label: string
  text: string
}

const GAP = 6
const EDGE = 8
// Matches max-width in .infotip__bubble; used to keep the note on screen.
const MAX_WIDTH = 288
const FLIP_BELOW = 140

/** A small ⓘ button that shows a note on hover or keyboard focus.
 *
 * The note is rendered at the end of the page with fixed positioning so a
 * scrolling container (like the column table) can't clip it.
 */
export function InfoTip({ label, text }: InfoTipProps) {
  const id = useId()
  const buttonRef = useRef<HTMLButtonElement>(null)
  const [style, setStyle] = useState<CSSProperties | null>(null)

  function show() {
    const button = buttonRef.current
    if (!button) return
    const rect = button.getBoundingClientRect()
    const half = Math.min(MAX_WIDTH, window.innerWidth * 0.7) / 2
    const center = rect.left + rect.width / 2
    const left = Math.min(Math.max(center, half + EDGE), window.innerWidth - half - EDGE)
    const above = rect.bottom + FLIP_BELOW > window.innerHeight
    setStyle(
      above
        ? { left, top: rect.top - GAP, transform: 'translate(-50%, -100%)' }
        : { left, top: rect.bottom + GAP, transform: 'translateX(-50%)' },
    )
  }

  const hide = () => setStyle(null)
  const open = style !== null

  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') hide()
    }
    // A fixed note would drift away from its button while scrolling.
    window.addEventListener('keydown', onKey)
    window.addEventListener('scroll', hide, true)
    window.addEventListener('resize', hide)
    return () => {
      window.removeEventListener('keydown', onKey)
      window.removeEventListener('scroll', hide, true)
      window.removeEventListener('resize', hide)
    }
  }, [open])

  return (
    <>
      <button
        ref={buttonRef}
        type="button"
        className="infotip__button"
        aria-label={label}
        aria-describedby={id}
        onMouseEnter={show}
        onMouseLeave={hide}
        onFocus={show}
        onBlur={hide}
      >
        <span aria-hidden="true">i</span>
      </button>
      {createPortal(
        <span
          role="tooltip"
          id={id}
          className={`infotip__bubble${open ? ' infotip__bubble--open' : ''}`}
          style={style ?? undefined}
        >
          {text}
        </span>,
        document.body,
      )}
    </>
  )
}
