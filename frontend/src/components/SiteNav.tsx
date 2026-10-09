import { Logo } from './Logo'

interface SiteNavProps {
  /** The landing page offers its sections; the analysis page only offers the way back. */
  variant: 'landing' | 'analysis'
  onHome: () => void
  /** Opens and closes the connectors panel, which sits beside either page. */
  onConnectors: () => void
  connectorsOpen: boolean
}

export function SiteNav({ variant, onHome, onConnectors, connectorsOpen }: SiteNavProps) {
  const onLanding = variant === 'landing'
  return (
    <header className="site-nav">
      <div className="site-nav__inner">
        <button type="button" className="site-nav__brand" onClick={onHome}>
          <Logo size={38} />
          <span className="site-nav__wordmark">Tidy Lab</span>
        </button>
        <nav className="site-nav__links" aria-label="Pages and sections">
          <button
            type="button"
            className={`site-nav__link${onLanding ? ' site-nav__link--on' : ''}`}
            onClick={onHome}
            aria-current={onLanding ? 'page' : undefined}
          >
            Home
          </button>
          <button
            type="button"
            className={`site-nav__link${connectorsOpen ? ' site-nav__link--on' : ''}`}
            onClick={onConnectors}
            aria-expanded={connectorsOpen}
            aria-controls="connectors-panel"
          >
            Connectors
          </button>
          {onLanding && (
            <>
              <a className="site-nav__link" href="#features">
                Features
              </a>
              <a className="site-nav__link" href="#faq">
                FAQ
              </a>
            </>
          )}
        </nav>
      </div>
    </header>
  )
}
