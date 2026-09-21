interface LogoProps {
  size?: number
}

/**
 * The mark: a chamfered badge around an italic TL. Drawn rather than loaded so
 * it stays sharp at any size and takes its colour from the surrounding text.
 */
export function Logo({ size = 36 }: LogoProps) {
  return (
    <svg
      className="logo"
      width={size}
      height={size}
      viewBox="0 0 40 40"
      fill="none"
      aria-hidden="true"
      focusable="false"
    >
      <path
        d="M9.5 2.5h21l7 7v21l-7 7h-21l-7-7v-21l7-7Z"
        stroke="currentColor"
        strokeWidth="2.6"
        strokeLinejoin="round"
      />
      <g transform="translate(2.6 0) skewX(-9)" fill="currentColor">
        <path d="M7.6 12h12.6v3.7h-4.5V28h-3.7V15.7H7.6V12Z" />
        <path d="M21.6 12h3.7v12.3h7.1V28H21.6V12Z" />
      </g>
    </svg>
  )
}
