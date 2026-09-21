import { formatBytes } from '../upload/format'
import { FAQ } from './copy'

interface FaqProps {
  /** The real cap, as the server reports it. Null until the limits query answers. */
  maxBytes: number | null
}

export function Faq({ maxBytes }: FaqProps) {
  return (
    <section className="section faq" id="faq" aria-labelledby="faq-title">
      <p className="eyebrow">{FAQ.eyebrow}</p>
      <h2 id="faq-title" className="section__title">
        {FAQ.title}
      </h2>
      <div className="faq__list">
        {FAQ.items.map((item) => (
          <details key={item.question} className="faq__item" name="faq">
            <summary className="faq__question">{item.question}</summary>
            <p className="faq__answer">
              {item.answer}
              {'showsLimit' in item && maxBytes != null && (
                <> The limit here is {formatBytes(maxBytes)} a file.</>
              )}
            </p>
          </details>
        ))}
      </div>
    </section>
  )
}
