import type { ColumnProfile, DatasetSummary } from '../api/client'

export function column(overrides: Partial<ColumnProfile> = {}): ColumnProfile {
  return {
    name: 'Email',
    position: 0,
    physical_type: 'text',
    semantic_role: 'contact',
    role_confidence: 1,
    role_note: '100% of filled values look like email addresses.',
    flags: [],
    row_count: 3,
    non_blank_count: 3,
    fill_rate: 1,
    distinct_count: 3,
    uniqueness: 1,
    patterns: [],
    min_value: null,
    max_value: null,
    sample_values: ['a@x.com', 'b@x.com', 'c@x.com', 'd@x.com'],
    ...overrides,
  }
}

export function dataset(overrides: Partial<DatasetSummary> = {}): DatasetSummary {
  return {
    id: 'abc123',
    filename: 'people.csv',
    format: 'csv',
    sheet_name: null,
    available_sheets: [],
    header_mode: 'auto',
    header_detected: true,
    row_count: 1020,
    column_count: 2,
    empty_rows_skipped: 0,
    columns: [
      column(),
      column({
        name: 'Salary',
        position: 1,
        semantic_role: 'measure',
        role_note: '98% of filled values are numbers, so they can be added up and averaged.',
        fill_rate: 0.976,
        distinct_count: 979,
        min_value: '50047.32',
        max_value: '119971.65',
        sample_values: ['N/A', '52031.74'],
      }),
    ],
    ...overrides,
  }
}

export function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}
