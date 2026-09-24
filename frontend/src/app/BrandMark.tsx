import { useId } from 'react'

/**
 * RAGLabs mark: a katana on a violet tile that is cleanly cut along the blade (documents, sliced into chunks).
 * Same artwork as public/favicon.svg; ids are per-instance so several marks can share a page.
 */
export function BrandMark({ size = 36, className }: { size?: number; className?: string }) {
  const id = useId()
  const bg = `${id}-bg`
  const tile = `${id}-tile`
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" className={className} aria-hidden>
      <defs>
        <linearGradient id={bg} x1="4" y1="2" x2="60" y2="62" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#8B7CFF" />
          <stop offset=".5" stopColor="#6246EA" />
          <stop offset="1" stopColor="#3B1C8C" />
        </linearGradient>
        <clipPath id={tile}>
          <rect width="64" height="64" rx="15" />
        </clipPath>
      </defs>
      <g clipPath={`url(#${tile})`}>
        <rect width="64" height="64" fill={`url(#${bg})`} />
        <path d="M64 0V26L28 64H0Z" fill="#000" opacity=".2" />
        <path d="M59 -3L-3 59" stroke="#C9BEFF" strokeWidth="1.3" opacity=".75" />
      </g>
      <path d="M27 42.4C36 37 46 27.5 55 9C47.5 21.5 36.5 31 22.6 37.6Z" fill="#fff" />
      <circle cx="23.4" cy="41.6" r="5.4" fill="#fff" />
      <circle cx="23.4" cy="41.6" r="1.7" fill="#5438D8" />
      <path d="M19.6 45.4L10.4 54.6" stroke="#fff" strokeWidth="6" strokeLinecap="round" />
      <path d="M11.7 51.1l3.2 3.2M14.5 48.3l3.2 3.2M17.3 45.5l2.4 2.4" stroke="#5438D8" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  )
}
