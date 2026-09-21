const LABEL =
  'A sketch of a messy table becoming a tidy one: stray spaces, three spellings of one team ' +
  'name, dates stored as text, an N/A standing in for a blank, and a repeated row all resolved.'

const HEAD = ['Name', 'Team', 'Joined']

/** Middle dots stand in for stray spaces, so the mess is visible without any figures. */
const BEFORE: { cells: string[]; dirty: boolean[]; dropped?: boolean }[] = [
  { cells: ['·Ann·', 'sales', '(text)'], dirty: [true, true, true] },
  { cells: ['Bo', 'Sales', '(text)'], dirty: [false, false, true] },
  { cells: ['Ann', 'SALES', 'N/A'], dirty: [false, true, true] },
  { cells: ['Bo', 'Sales', '(text)'], dirty: [false, false, true], dropped: true },
]

const AFTER = [
  ['Ann', 'Sales', '(date)'],
  ['Bo', 'Sales', '(date)'],
  ['Ann', 'Sales', 'blank'],
]

export function HeroDiagram() {
  return (
    <div className="herodiagram" role="img" aria-label={LABEL}>
      <div className="herodiagram__card">
        <p className="herodiagram__caption">What you have</p>
        <div className="herodiagram__grid">
          {HEAD.map((name) => (
            <span key={name} className="herodiagram__cell herodiagram__cell--head">
              {name}
            </span>
          ))}
          {BEFORE.map((row, index) =>
            row.cells.map((value, column) => (
              <span
                key={`${index}-${column}`}
                className={
                  'herodiagram__cell' +
                  (row.dirty[column] ? ' herodiagram__cell--dirty' : '') +
                  (row.dropped ? ' herodiagram__cell--dropped' : '')
                }
              >
                {value}
              </span>
            )),
          )}
        </div>
      </div>

      <span className="herodiagram__arrow" aria-hidden="true">
        →
      </span>

      <div className="herodiagram__card herodiagram__card--after">
        <p className="herodiagram__caption">What you get</p>
        <div className="herodiagram__grid">
          {HEAD.map((name) => (
            <span key={name} className="herodiagram__cell herodiagram__cell--head">
              {name}
            </span>
          ))}
          {AFTER.map((row, index) =>
            row.map((value, column) => (
              <span key={`${index}-${column}`} className="herodiagram__cell">
                {value}
              </span>
            )),
          )}
        </div>
      </div>
    </div>
  )
}
