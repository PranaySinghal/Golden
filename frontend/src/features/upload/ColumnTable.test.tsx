import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { column, dataset } from '../../test/fixtures'
import { ColumnTable } from './ColumnTable'

afterEach(cleanup)

describe('ColumnTable', () => {
  it('shows what each column holds, with only the first few examples', () => {
    render(<ColumnTable columns={dataset().columns} />)

    const rows = screen.getAllByRole('row')
    expect(rows).toHaveLength(3)
    const salary = within(rows[2])
    expect(salary.getByText('Number')).toBeTruthy()
    expect(salary.getByText('98%')).toBeTruthy()
    expect(salary.getByText('979')).toBeTruthy()
    expect(salary.getByText('50047.32')).toBeTruthy()
    expect(salary.getByText('– 119971.65')).toBeTruthy()
    expect(within(rows[1]).queryByText('d@x.com')).toBeNull()
  })

  it('explains each kind in a note tied to its button', () => {
    render(<ColumnTable columns={dataset().columns} />)

    const button = screen.getByRole('button', { name: 'Why Salary is Number' })
    const note = document.getElementById(button.getAttribute('aria-describedby')!)

    expect(note?.textContent).toContain('can be added up and averaged')
    expect(note?.getAttribute('role')).toBe('tooltip')
    const isOpen = () => note?.classList.contains('infotip__bubble--open')
    expect(isOpen()).toBe(false)

    fireEvent.mouseEnter(button)
    expect(isOpen()).toBe(true)
    fireEvent.mouseLeave(button)
    expect(isOpen()).toBe(false)

    fireEvent.focus(button)
    expect(isOpen()).toBe(true)
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(isOpen()).toBe(false)
  })

  it('labels an all-blank column as empty and explains why', () => {
    const blank = column({
      name: 'Notes',
      semantic_role: 'text',
      non_blank_count: 0,
      fill_rate: 0,
      distinct_count: 0,
      sample_values: [],
      role_note: "All 3 rows are empty in this column, so we can't tell what it's meant to hold.",
    })

    render(<ColumnTable columns={[blank]} />)

    const button = screen.getByRole('button', { name: 'Why Notes is empty' })
    expect(screen.getByText('Empty')).toBeTruthy()
    expect(screen.getByText('No values')).toBeTruthy()
    expect(document.getElementById(button.getAttribute('aria-describedby')!)?.textContent).toMatch(
      /All 3 rows are empty/,
    )
  })
})
