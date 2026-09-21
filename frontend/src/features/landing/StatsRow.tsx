import { STATS } from './copy'

export function StatsRow() {
  return (
    <section className="stats" aria-label="What to expect">
      <dl className="stats__grid">
        {STATS.map((stat) => (
          <div key={stat.label} className="stats__item">
            <dt className="stats__figure">{stat.figure}</dt>
            <dd className="stats__label">{stat.label}</dd>
          </div>
        ))}
      </dl>
    </section>
  )
}
