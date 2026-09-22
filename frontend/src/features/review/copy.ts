import type { StepView, Tier } from '../../api/client'
import { formatCount } from '../upload/format'

interface TierCopy {
  title: string
  blurb: string
  empty: string
}

/** Headings for the three groups of cards. Business language, no tier names. */
export const TIERS: Record<Tier, TierCopy> = {
  ask: {
    title: 'Needs your decision',
    blurb: 'These could go either way. Your answer decides what the numbers say.',
    empty: 'Nothing to decide on this file.',
  },
  likely: {
    title: 'Suggested',
    blurb: 'Very likely right, but worth a look before they go in.',
    empty: 'No suggestions for this file.',
  },
  safe: {
    title: 'Already fixed',
    blurb: "These can't change what your data means, so they're done.",
    empty: 'Nothing was fixed automatically.',
  },
}

export const TIER_ORDER: Tier[] = ['ask', 'likely', 'safe']

export function affected(rows: number): string {
  if (rows <= 0) return ''
  return `${formatCount(rows)} ${rows === 1 ? 'row' : 'rows'} affected`
}

/** What came of re-using steps saved from another file. */
export function reusedSteps(count: number, source: string | null): string {
  const steps = `${formatCount(count)} ${count === 1 ? 'step' : 'steps'}`
  const from = source ? ` saved from “${source}”` : ' you saved earlier'
  // Anything certain we found in this file is applied too, so the list can be
  // longer than what was saved. Better to say so than to look like a miscount.
  return `We re-used the ${steps}${from}, plus anything certain we found here.`
}

export const REUSE_REFUSED = "We couldn't use those steps on this file, so nothing was changed."

/** What a step did, once the recipe ran. */
export function stepEffect(step: StepView): string | null {
  if (step.status === 'blocked') return step.reason ?? "This step can't run right now."
  if (step.status === 'disabled') return 'Turned off'
  const parts: string[] = []
  if (step.cells_changed) {
    parts.push(`${formatCount(step.cells_changed)} ${step.cells_changed === 1 ? 'value' : 'values'} changed`)
  }
  if (step.rows_set_aside) {
    parts.push(`${formatCount(step.rows_set_aside)} ${step.rows_set_aside === 1 ? 'row' : 'rows'} set aside`)
  }
  if (parts.length === 0) return 'Nothing to change'
  return parts.join(' · ')
}

export function rowsKept(rows: number, setAside: number): string {
  const kept = `${formatCount(rows)} ${rows === 1 ? 'row' : 'rows'} kept`
  if (setAside <= 0) return kept
  return `${kept} · ${formatCount(setAside)} set aside`
}
