// Second Mind's mark: a note with a footnote marker, since every answer points back
// to a cited source. Same geometry as the app icon
// (src-tauri/icons/icon.svg), cropped to the two circles; the color comes
// from currentColor, so each place sets it with CSS.
export default function LogoMark({ size = 24, className }: { size?: number; className?: string }) {
  return (
    <svg className={className} width={size} height={size} viewBox="271 241 520 520" aria-hidden="true">
      <circle cx="478" cy="556" r="200" fill="currentColor" />
      <circle cx="712" cy="318" r="72" fill="currentColor" />
    </svg>
  );
}
