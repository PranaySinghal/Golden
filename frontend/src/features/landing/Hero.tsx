import type { DatasetSummary } from '../../api/client'
import { UploadPanel } from '../upload/UploadPanel'
import { HeroDiagram } from './HeroDiagram'
import { HERO } from './copy'

interface HeroProps {
  onUploaded: (dataset: DatasetSummary) => void
}

export function Hero({ onUploaded }: HeroProps) {
  return (
    <section className="hero">
      <div className="hero__head">
        <p className="eyebrow">{HERO.eyebrow}</p>
        <h1 className="hero__headline">
          {HERO.headlineLead}{' '}
          <em className="hero__accent">
            {HERO.headlineAccent}
            <svg
              className="hero__swash"
              viewBox="0 0 300 12"
              preserveAspectRatio="none"
              aria-hidden="true"
              focusable="false"
            >
              <path
                d="M2 8.5c48-5 96-6.5 146-4.5 34 1.4 68 3.4 106 5.5"
                fill="none"
                stroke="currentColor"
                strokeWidth="3"
                strokeLinecap="round"
              />
            </svg>
          </em>
        </h1>
        <p className="hero__subhead">{HERO.subhead}</p>
      </div>

      <div className="hero__body">
        <div className="hero__figure">
          <HeroDiagram />
        </div>
        <div className="hero__upload">
          <UploadPanel onUploaded={onUploaded} />
        </div>
      </div>
    </section>
  )
}
