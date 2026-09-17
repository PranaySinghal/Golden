import { describe, expect, it } from 'vitest'

import { column } from '../../test/fixtures'
import { describeRows, formatBytes, formatRange, formatShare } from './format'

describe('formatShare', () => {
  it.each([
    [1, '100%'],
    [0, '0%'],
    [0.976, '98%'],
    [0.996, '>99%'],
    [0.004, '<1%'],
  ])('%s → %s', (share, expected) => {
    expect(formatShare(share)).toBe(expected)
  })
})

describe('formatBytes', () => {
  it.each([
    [50 * 1024 * 1024, '50 MB'],
    [1.5 * 1024 * 1024, '1.5 MB'],
    [2048, '2 KB'],
    [10, '1 KB'],
  ])('%s → %s', (bytes, expected) => {
    expect(formatBytes(bytes)).toBe(expected)
  })
})

describe('formatRange', () => {
  it('shows both ends, one value, or nothing', () => {
    expect(formatRange(column({ min_value: '1', max_value: '9' }))).toEqual(['1', '9'])
    expect(formatRange(column({ min_value: '5', max_value: '5' }))).toEqual(['5'])
    expect(formatRange(column())).toBeNull()
  })
})

describe('describeRows', () => {
  it('uses singular words for one', () => {
    expect(describeRows(1, 1)).toBe('1 row · 1 column')
    expect(describeRows(1020, 12)).toBe('1,020 rows · 12 columns')
  })
})
