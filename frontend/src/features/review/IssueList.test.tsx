import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import type { IssueView } from '../../api/client'
import { issue } from '../../test/fixtures'
import { IssueList, SAME_KIND_SHOWN } from './IssueList'

function blanks(count: number, tier: IssueView['tier'] = 'likely'): IssueView[] {
  return Array.from({ length: count }, (_, index) =>
    issue({
      id: `blank-${tier}-${index}`,
      detector: 'missing_values',
      tier,
      title: `Rows have no "m${index}"`,
    }),
  )
}

function renderList(issues: IssueView[], reveal: string | null = null) {
  const client = new QueryClient()
  return render(
    <QueryClientProvider client={client}>
      <IssueList
        datasetId="abc"
        issues={issues}
        busyWith={() => false}
        errorFor={() => null}
        onAccept={() => {}}
        onReject={() => {}}
        reveal={reveal}
      />
    </QueryClientProvider>,
  )
}

const cards = () => screen.getAllByRole('article').length

afterEach(cleanup)

describe('IssueList', () => {
  it('shows a few cards of one kind and folds the rest away', () => {
    const other = issue({ id: 'spaces', detector: 'extra_spaces', tier: 'likely', title: 'Spaces' })

    renderList([...blanks(60), other])

    // The section still says how many there are in all.
    const section = screen.getByRole('region', { name: /61/ })
    expect(within(section).getAllByRole('article')).toHaveLength(SAME_KIND_SHOWN + 1)
    // A different kind of card is never hidden behind sixty of another.
    expect(screen.getByRole('heading', { name: 'Spaces' })).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: 'Show 57 more like these' }))

    expect(cards()).toBe(61)
    expect(screen.queryByRole('button', { name: /more like/ })).toBeNull()
  })

  it('leaves a handful of the same kind alone', () => {
    renderList(blanks(SAME_KIND_SHOWN))

    expect(cards()).toBe(SAME_KIND_SHOWN)
    expect(screen.queryByRole('button', { name: /more like/ })).toBeNull()
  })

  it('folds each section on its own', () => {
    renderList([...blanks(5, 'likely'), ...blanks(4, 'ask')])

    expect(screen.getByRole('button', { name: 'Show 2 more like these' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Show 1 more like this' })).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: 'Show 1 more like this' }))

    // Opening one section's cards leaves the other folded.
    expect(cards()).toBe(SAME_KIND_SHOWN + 4)
    expect(screen.getByRole('button', { name: 'Show 2 more like these' })).toBeTruthy()
  })

  it('shows a folded card when something links to it', () => {
    renderList(blanks(10), 'blank-likely-8')

    expect(screen.getByRole('heading', { name: 'Rows have no "m8"' })).toBeTruthy()
    expect(cards()).toBe(10)
  })
})
