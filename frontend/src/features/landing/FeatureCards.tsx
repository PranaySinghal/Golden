import { FEATURES } from './copy'

export function FeatureCards() {
  return (
    <section className="section features" id="features" aria-labelledby="features-title">
      <p className="eyebrow">{FEATURES.eyebrow}</p>
      <h2 id="features-title" className="section__title">
        {FEATURES.title}
      </h2>
      <p className="section__lede">{FEATURES.lede}</p>
      <div className="features__grid">
        {FEATURES.cards.map((card) => (
          <article key={card.title} className="feature">
            <h3 className="feature__title">{card.title}</h3>
            <p className="feature__body">{card.body}</p>
          </article>
        ))}
      </div>
    </section>
  )
}
