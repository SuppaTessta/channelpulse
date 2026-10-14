/** The ChannelPulse mark: a pulse line riding a river curve (Gangasagar, where the river meets the sea). */
export function BrandMark({ size = 32, animate = false }: { size?: number; animate?: boolean }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden className={animate ? "cp-mark-draw" : undefined}>
      <rect x="0.5" y="0.5" width="31" height="31" rx="9" fill="var(--accent-soft)" stroke="color-mix(in oklab, var(--accent) 40%, transparent)" />
      <path
        d="M5 21c4 0 5-3 8-3s4 3 7 3 4-2 7-2"
        fill="none"
        stroke="color-mix(in oklab, var(--accent) 45%, transparent)"
        strokeWidth="1.5"
        strokeLinecap="round"
        pathLength={1}
      />
      <path d="M5 15h5l2.5-6 4 13 3-9 1.6 2H27" fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" pathLength={1} />
    </svg>
  );
}
