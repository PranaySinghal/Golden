import type {
  ColumnProfile,
  DatasetSummary,
  IssueListResponse,
  IssueView,
  Preview,
  RecipeResponse,
  StepView,
} from '../api/client'

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

export function step(overrides: Partial<StepView> = {}): StepView {
  return {
    id: 'step-1',
    type: 'cast_number',
    label: 'Read as numbers',
    description: 'Read "Salary" as numbers',
    columns: ['Salary'],
    enabled: true,
    status: 'applied',
    reason: null,
    rows_set_aside: 0,
    cells_changed: 24,
    issue_id: 'issue-safe',
    ...overrides,
  }
}

export function recipe(overrides: Partial<RecipeResponse> = {}): RecipeResponse {
  return {
    steps: [step()],
    can_undo: false,
    row_count: 1020,
    set_aside_count: 0,
    columns: [{ name: 'Salary', kind: 'number' }],
    ...overrides,
  }
}

export function issue(overrides: Partial<IssueView> = {}): IssueView {
  return {
    id: 'issue-likely',
    detector: 'extra_spaces',
    columns: ['First_Name'],
    title: '38 names have extra spaces around them',
    explanation: 'Extra spaces split one name into two groups when you count them.',
    examples: [' Ann ', 'Bo  '],
    affected_rows: 38,
    tier: 'likely',
    impact: 0.4,
    ask: null,
    state: 'available',
    chosen_choice_id: null,
    step_ids: [],
    ...overrides,
  }
}

export function askIssue(overrides: Partial<IssueView> = {}): IssueView {
  return issue({
    id: 'issue-ask',
    detector: 'placeholders',
    columns: ['Salary'],
    title: '24 "Salary" values say "N/A" instead of a number',
    tier: 'ask',
    impact: 0.8,
    ask: {
      prompt: 'What should "N/A" mean in "Salary"?',
      choices: [
        {
          id: 'missing',
          label: 'Treat them as missing',
          description: 'Leave them out of totals and averages.',
          steps: [],
          recommended: true,
        },
        {
          id: 'zero',
          label: 'Treat them as zero',
          description: 'Count them as 0, which pulls the average down.',
          steps: [],
          recommended: false,
        },
      ],
    },
    ...overrides,
  })
}

export function issueList(overrides: Partial<IssueListResponse> = {}): IssueListResponse {
  return {
    issues: [askIssue(), issue()],
    counts: { safe: 1, likely: 1, ask: 1 },
    needs_decision: 1,
    recipe: recipe(),
    ...overrides,
  }
}

export function preview(overrides: Partial<Preview> = {}): Preview {
  return {
    columns: ['First_Name'],
    rows: [
      {
        row_id: 3,
        cells: { First_Name: { before: ' Ann ', after: 'Ann', changed: true } },
        set_aside: false,
      },
    ],
    changed_rows: 38,
    set_aside_rows: 0,
    note: null,
    ...overrides,
  }
}

export function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}
