import { describe, expect, it } from 'vitest'

import { breakdownCard, card } from '../../test/fixtures'
import { chartRows } from './chartData'
import { changeDirection, describeChange, formatAnswer, togetherNote, whyLead } from './format'

describe('formatAnswer', () => {
  it('keeps counts whole', () => {
    expect(formatAnswer(1020, 'count')).toBe('1,020')
    expect(formatAnswer(928.0, 'count_distinct')).toBe('928')
  })

  it('shows two decimals for money-like answers', () => {
    expect(formatAnswer(85155.055, 'avg')).toBe('85,155.06')
    expect(formatAnswer(20686.29, 'sum')).toBe('20,686.29')
  })

  it('leaves whole numbers whole', () => {
    expect(formatAnswer(1500, 'sum')).toBe('1,500')
  })

  it('shows a dash when there is no answer', () => {
    expect(formatAnswer(null, 'avg')).toBe('—')
  })
})

describe('describeChange', () => {
  it('says which way it moved and by how much', () => {
    expect(describeChange(card())).toBe('2,003.65 lower (2.4%)')
  })

  it('says higher when it went up', () => {
    const up = card({ change: 10, relative_change: 0.5, measure: 'count' })
    expect(describeChange(up)).toBe('10 higher (50.0%)')
  })

  it('has nothing to say when nothing moved', () => {
    expect(describeChange(card({ change: 0 }))).toBeNull()
    expect(describeChange(card({ change: null }))).toBeNull()
  })

  it('handles a change too small to round to a tenth', () => {
    const tiny = card({ change: 0.4, relative_change: 0.0000004, measure: 'avg' })
    expect(describeChange(tiny)).toContain('under 0.1%')
  })

  it('marks the direction for styling', () => {
    expect(changeDirection(card())).toBe('down')
    expect(changeDirection(card({ change: 3 }))).toBe('up')
    expect(changeDirection(card({ change: null }))).toBe('flat')
  })
})

describe('why', () => {
  it('claims a cause when it was measured', () => {
    expect(whyLead(card())).toBe('Caused by')
  })

  it('hedges when the cause was only narrowed down', () => {
    expect(whyLead(card({ why: { step_ids: ['a'], groups: [], method: 'estimated' } }))).toBe(
      'Likely caused by',
    )
  })

  it('explains steps that only matter together', () => {
    const together = card({
      why: {
        step_ids: ['a', 'b'],
        groups: [{ step_ids: ['a', 'b'], together: true, contribution: 0.5 }],
        method: 'exact',
      },
    })

    expect(whyLead(together)).toBe('Caused by these together')
    expect(togetherNote(together)).toContain('it takes both')
  })

  it('says nothing about togetherness when one step did it', () => {
    expect(togetherNote(card())).toBeNull()
  })
})

describe('chartRows', () => {
  it('puts the biggest group first', () => {
    const rows = chartRows(breakdownCard())

    expect(rows.map((row) => row.label)).toEqual(['Sales', 'Support'])
    expect(rows[0]).toMatchObject({ before: 20, after: 30 })
  })

  it('keeps a trend in the order the periods came in', () => {
    const trend = breakdownCard({
      kind: 'trend',
      groups: [
        { label: '2024-01', before: 5, after: 9, status: 'changed' },
        { label: '2024-02', before: 20, after: 11, status: 'changed' },
      ],
    })

    expect(chartRows(trend).map((row) => row.label)).toEqual(['2024-01', '2024-02'])
  })

  it('draws a missing count as the zero it is', () => {
    const appeared = breakdownCard({
      groups: [{ label: 'North', before: null, after: 12, status: 'appeared' }],
    })

    expect(chartRows(appeared)[0].before).toBe(0)
  })

  it('draws no bar for an average that had no value', () => {
    const appeared = breakdownCard({
      measure: 'avg',
      groups: [{ label: 'North', before: null, after: 85000, status: 'appeared' }],
    })

    expect(chartRows(appeared)[0].before).toBeNull()
  })

  it('shows only a handful of groups', () => {
    const many = breakdownCard({
      groups: Array.from({ length: 20 }, (_, index) => ({
        label: `g${index}`,
        before: index,
        after: index,
        status: 'same' as const,
      })),
    })

    expect(chartRows(many)).toHaveLength(8)
  })
})
