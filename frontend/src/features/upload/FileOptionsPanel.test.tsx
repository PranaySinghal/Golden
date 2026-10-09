import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { DatasetSummary } from '../../api/client'
import { dataset } from '../../test/fixtures'
import { FileOptionsPanel } from './FileOptionsPanel'

function renderPanel(
  overrides: Partial<DatasetSummary> = {},
  props: { onReread?: () => void; rereading?: boolean; rereadError?: string | null; stepCount?: number } = {},
) {
  const onReread = props.onReread ?? vi.fn()
  render(
    <FileOptionsPanel
      dataset={dataset(overrides)}
      onReread={onReread}
      rereading={props.rereading ?? false}
      rereadError={props.rereadError ?? null}
      stepCount={props.stepCount ?? 0}
    />,
  )
  return onReread
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('FileOptionsPanel', () => {
  it('asks for the file again when "First row has column names" is unticked', () => {
    const onReread = vi.fn()
    renderPanel({}, { onReread })

    const checkbox = screen.getByRole('checkbox', { name: 'First row has column names' })
    expect((checkbox as HTMLInputElement).checked).toBe(true)
    fireEvent.click(checkbox)

    expect(onReread).toHaveBeenCalledWith({ sheet: null, header: 'data' })
  })

  it('offers a sheet picker only for Excel files with several sheets', () => {
    const onReread = vi.fn()
    renderPanel(
      {
        filename: 'book.xlsx',
        format: 'xlsx',
        sheet_name: 'Summary',
        available_sheets: ['Summary', 'Details'],
      },
      { onReread },
    )

    fireEvent.change(screen.getByRole('combobox', { name: 'Sheet' }), {
      target: { value: 'Details' },
    })

    expect(onReread).toHaveBeenCalledWith({ sheet: 'Details', header: 'auto' })
  })

  it('has no sheet picker for CSV files', () => {
    renderPanel()

    expect(screen.queryByRole('combobox')).toBeNull()
  })

  it('checks first when a re-read would throw work away', () => {
    const confirm = vi.fn((_message: string) => false)
    vi.stubGlobal('confirm', confirm)
    const onReread = vi.fn()
    renderPanel({}, { onReread, stepCount: 3 })

    fireEvent.click(screen.getByRole('checkbox', { name: 'First row has column names' }))

    expect(confirm.mock.calls[0][0]).toContain('all 3 fixes')
    expect(onReread).not.toHaveBeenCalled()
  })

  it('re-reads once the warning is accepted', () => {
    vi.stubGlobal('confirm', vi.fn(() => true))
    const onReread = vi.fn()
    renderPanel({}, { onReread, stepCount: 1 })

    fireEvent.click(screen.getByRole('checkbox', { name: 'First row has column names' }))

    expect(onReread).toHaveBeenCalledWith({ sheet: null, header: 'data' })
  })

  it('locks the controls while it re-reads', () => {
    renderPanel({}, { rereading: true })

    expect(
      (screen.getByRole('checkbox', { name: 'First row has column names' }) as HTMLInputElement)
        .disabled,
    ).toBe(true)
    expect(screen.getByRole('status').textContent).toContain('Reading the file again')
  })

  it('shows the reason a re-read failed', () => {
    renderPanel({}, { rereadError: "We can't open that sheet." })

    expect(screen.getByRole('alert').textContent).toContain("We can't open that sheet.")
  })

  it('says which title lines above the column names were left out', () => {
    renderPanel({ title_rows_skipped: ['Customer survey', 'Exported 2 November'] })

    const note = screen.getByText(/above the column names were left out as a title/)
    expect(note.textContent).toContain('2 lines')
    expect(note.textContent).toContain('“Customer survey”, “Exported 2 November”')
  })

  it('says how many empty rows were skipped', () => {
    renderPanel({ empty_rows_skipped: 3 })

    expect(screen.getByText(/3 empty rows were skipped/)).toBeTruthy()
  })
})
