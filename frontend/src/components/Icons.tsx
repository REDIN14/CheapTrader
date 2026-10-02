// TradingView-style icon set.
//
// Every glyph is drawn on a 28x28 grid with thin round-capped strokes and uses
// `currentColor`, so one CSS colour drives the idle / hover / active state.
//
// Only icons that some component actually renders are exported here — there are
// no decorative leftovers.

import type { SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement> & { size?: number };

function Icon({ size = 28, children, ...rest }: IconProps) {
  return (
    <svg
      viewBox="0 0 28 28"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth={1.2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      {...rest}
    >
      {children}
    </svg>
  );
}

/* -- branding ------------------------------------------------------- */

/** The CheapTrader mark: two candles on the accent blue. */
export const BrandMark = ({ size = 28, ...rest }: IconProps) => (
  <svg viewBox="0 0 28 28" width={size} height={size} aria-hidden="true" focusable="false" {...rest}>
    <rect x="1" y="1" width="26" height="26" rx="6.5" fill="#2962ff" />
    <path
      d="M10.5 5.8v3.9M10.5 19.2v3M17.5 4.8v4M17.5 15.6v4.6"
      stroke="#fff"
      strokeWidth="1.7"
      strokeLinecap="round"
    />
    <rect x="8.2" y="9.7" width="4.6" height="9.5" rx="1.1" fill="#fff" />
    <rect x="15.2" y="9" width="4.6" height="6.6" rx="1.1" fill="#fff" fillOpacity="0.6" />
  </svg>
);

/* -- generic controls ---------------------------------------------- */

export const ChevronDown = ({ size = 16, ...rest }: IconProps) => (
  <Icon size={size} strokeWidth={1.5} {...rest}>
    <path d="M9 11.5l5 5 5-5" />
  </Icon>
);

export const ChevronUp = ({ size = 16, ...rest }: IconProps) => (
  <Icon size={size} strokeWidth={1.5} {...rest}>
    <path d="M9 16.5l5-5 5 5" />
  </Icon>
);

export const CloseIcon = ({ size = 20, ...rest }: IconProps) => (
  <Icon size={size} strokeWidth={1.5} {...rest}>
    <path d="M8.5 8.5l11 11M19.5 8.5l-11 11" />
  </Icon>
);

export const CheckIcon = ({ size = 16, ...rest }: IconProps) => (
  <Icon size={size} strokeWidth={1.8} {...rest}>
    <path d="M7.5 14.5l4.5 4.5 8.5-9.5" />
  </Icon>
);

export const PlusIcon = ({ size = 20, ...rest }: IconProps) => (
  <Icon size={size} strokeWidth={1.5} {...rest}>
    <path d="M14 8v12M8 14h12" />
  </Icon>
);

export const SearchIcon = ({ size = 20, ...rest }: IconProps) => (
  <Icon size={size} strokeWidth={1.4} {...rest}>
    <circle cx="13" cy="13" r="5.6" />
    <path d="M17.2 17.2l4.6 4.6" />
  </Icon>
);

export const StarIcon = ({ size = 24, ...rest }: IconProps) => (
  <Icon size={size} strokeWidth={1.4} {...rest}>
    <path d="M14 5.6l2.6 5.4 5.9.8-4.3 4.2 1 5.9-5.2-2.8-5.2 2.8 1-5.9-4.3-4.2 5.9-.8L14 5.6z" />
  </Icon>
);

export const SettingsIcon = ({ size = 20, ...rest }: IconProps) => (
  <Icon size={size} strokeWidth={1.3} {...rest}>
    <path d="M14 5.6l7.3 4.2v8.4L14 22.4l-7.3-4.2V9.8L14 5.6z" />
    <circle cx="14" cy="14" r="3" />
  </Icon>
);

/** A monitor: the trading terminal. */
export const TerminalIcon = ({ size = 20, ...rest }: IconProps) => (
  <Icon size={size} {...rest}>
    <rect x="4.5" y="6.5" width="19" height="12.5" rx="1.5" />
    <path d="M10 23h8M14 19v4" />
    <path d="M9 15l2.4-2.4L13.5 14l3-3.3 2.5 2.6" />
  </Icon>
);

export const HelpIcon = ({ size = 28, ...rest }: IconProps) => (
  <Icon size={size} strokeWidth={1.2} {...rest}>
    <circle cx="14" cy="14" r="9.4" />
    <path d="M11.7 11.6a2.4 2.4 0 114.2 1.6c-.9.9-1.9 1.4-1.9 2.8" />
    <circle cx="14" cy="18.7" r="0.9" fill="currentColor" stroke="none" />
  </Icon>
);

export const CalendarIcon = ({ size = 20, ...rest }: IconProps) => (
  <Icon size={size} strokeWidth={1.3} {...rest}>
    <rect x="6.5" y="8" width="15" height="13.5" rx="1.8" />
    <path d="M6.5 12.4h15M10.6 5.8v4M17.4 5.8v4" />
  </Icon>
);

export const FitIcon = ({ size = 20, ...rest }: IconProps) => (
  <Icon size={size} strokeWidth={1.4} {...rest}>
    <path d="M5.5 14h17M9.6 10l-4.1 4 4.1 4M18.4 10l4.1 4-4.1 4" />
  </Icon>
);

/* -- header --------------------------------------------------------- */

export const FullscreenIcon = ({ size = 28, ...rest }: IconProps) => (
  <Icon size={size} strokeWidth={1.2} {...rest}>
    <path d="M7.5 11.5V9.8a2.3 2.3 0 012.3-2.3h1.7M16.5 7.5h1.7a2.3 2.3 0 012.3 2.3v1.7M20.5 16.5v1.7a2.3 2.3 0 01-2.3 2.3h-1.7M11.5 20.5H9.8a2.3 2.3 0 01-2.3-2.3v-1.7" />
  </Icon>
);

export const FullscreenExitIcon = ({ size = 28, ...rest }: IconProps) => (
  <Icon size={size} strokeWidth={1.2} {...rest}>
    <path d="M11.5 7.5v1.7a2.3 2.3 0 01-2.3 2.3H7.5M20.5 11.5h-1.7a2.3 2.3 0 01-2.3-2.3V7.5M16.5 20.5v-1.7a2.3 2.3 0 012.3-2.3h1.7M7.5 16.5h1.7a2.3 2.3 0 012.3 2.3v1.7" />
  </Icon>
);

export const IndicatorsIcon = ({ size = 28, ...rest }: IconProps) => (
  <Icon size={size} strokeWidth={1.2} {...rest}>
    <rect x="6.5" y="17.5" width="3" height="5" />
    <rect x="12.5" y="13.5" width="3" height="9" />
    <rect x="18.5" y="9.5" width="3" height="13" />
    <path d="M5.5 12.5l4.6-4.8 4 3.2 6.4-6" />
  </Icon>
);

export const ReplayIcon = ({ size = 28, ...rest }: IconProps) => (
  <Icon size={size} strokeWidth={1.2} {...rest}>
    <path d="M13.5 9.4L7.4 14l6.1 4.6V9.4z" />
    <path d="M21.5 9.4L15.4 14l6.1 4.6V9.4z" />
  </Icon>
);

/* -- right rail ----------------------------------------------------- */

export const WatchlistIcon = ({ size = 28, ...rest }: IconProps) => (
  <Icon size={size} strokeWidth={1.2} {...rest}>
    <path d="M9 6.6h10a1 1 0 011 1V22l-6-3.9L8 22V7.6a1 1 0 011-1z" />
    <path d="M11.4 11.2h5.2M11.4 14.4h5.2" />
  </Icon>
);

/* -- replay transport ----------------------------------------------- */

export const PlayIcon = ({ size = 28, ...rest }: IconProps) => (
  <svg viewBox="0 0 28 28" width={size} height={size} aria-hidden="true" {...rest}>
    <path d="M10 7.5l11 6.5-11 6.5z" fill="currentColor" />
  </svg>
);

export const PauseIcon = ({ size = 28, ...rest }: IconProps) => (
  <svg viewBox="0 0 28 28" width={size} height={size} aria-hidden="true" {...rest}>
    <rect x="9" y="7.5" width="3.6" height="13" rx="0.8" fill="currentColor" />
    <rect x="15.4" y="7.5" width="3.6" height="13" rx="0.8" fill="currentColor" />
  </svg>
);

export const StepIcon = ({ size = 28, ...rest }: IconProps) => (
  <svg viewBox="0 0 28 28" width={size} height={size} aria-hidden="true" {...rest}>
    <path d="M8 7.5l8 6.5-8 6.5z" fill="currentColor" />
    <rect x="17.4" y="7.5" width="2.8" height="13" rx="0.8" fill="currentColor" />
  </svg>
);

export const SkipEndIcon = ({ size = 28, ...rest }: IconProps) => (
  <svg viewBox="0 0 28 28" width={size} height={size} aria-hidden="true" {...rest}>
    <path d="M6 7.5l8 6.5-8 6.5z" fill="currentColor" />
    <path d="M14 7.5l8 6.5-8 6.5z" fill="currentColor" />
    <rect x="22.2" y="7.5" width="2.6" height="13" rx="0.8" fill="currentColor" />
  </svg>
);

/* -- replay: choosing a start, the report ---------------------------- */

/** The cut line of TradingView's "select bar": a pair of scissors. */
export const ScissorsIcon = ({ size = 22, ...rest }: IconProps) => (
  <Icon size={size} strokeWidth={1.3} {...rest}>
    <circle cx="9.4" cy="19.2" r="2.7" />
    <circle cx="18.6" cy="19.2" r="2.7" />
    <path d="M11.2 17.1L18.4 6.6M16.8 17.1L9.6 6.6" />
  </Icon>
);

/** A random bar. */
export const DiceIcon = ({ size = 22, ...rest }: IconProps) => (
  <Icon size={size} strokeWidth={1.3} {...rest}>
    <rect x="6.6" y="6.6" width="14.8" height="14.8" rx="3.2" />
    <circle cx="11" cy="11" r="1" fill="currentColor" stroke="none" />
    <circle cx="17" cy="11" r="1" fill="currentColor" stroke="none" />
    <circle cx="14" cy="14" r="1" fill="currentColor" stroke="none" />
    <circle cx="11" cy="17" r="1" fill="currentColor" stroke="none" />
    <circle cx="17" cy="17" r="1" fill="currentColor" stroke="none" />
  </Icon>
);

/** The performance report: bars rising from a baseline. */
export const ReportIcon = ({ size = 22, ...rest }: IconProps) => (
  <Icon size={size} strokeWidth={1.3} {...rest}>
    <path d="M7 21.2h14M9.6 21.2v-6M14 21.2V8.2M18.4 21.2v-9.4" />
  </Icon>
);

/** Start over (reset the paper account). */
export const ResetIcon = ({ size = 20, ...rest }: IconProps) => (
  <Icon size={size} strokeWidth={1.4} {...rest}>
    <path d="M7.4 11.2A7 7 0 1 1 7 15" />
    <path d="M6.8 6.6v4.8h4.8" />
  </Icon>
);

/** The handle a floating bar is moved by: two columns of dots. */
export const GripIcon = ({ size = 20, ...rest }: IconProps) => (
  <Icon size={size} {...rest}>
    {[9, 14, 19].map((y) => (
      <g key={y} fill="currentColor" stroke="none">
        <circle cx="11" cy={y} r="1.3" />
        <circle cx="17" cy={y} r="1.3" />
      </g>
    ))}
  </Icon>
);

/* -- drawing tools -------------------------------------------------- */

/** Trend line: a slanted line with a ring on each end. */
export const TrendLineIcon = ({ size = 28, ...rest }: IconProps) => (
  <Icon size={size} {...rest}>
    <path d="M9.4 18.6L18.6 9.4" />
    <circle cx="7.6" cy="20.4" r="2.1" />
    <circle cx="20.4" cy="7.6" r="2.1" />
  </Icon>
);

/** A position box: the letter on a tint, `L` for a long and `S` for a short. */
function PositionIcon({ letter, size = 28, ...rest }: IconProps & { letter: string }) {
  return (
    <Icon size={size} {...rest}>
      <rect x="5.6" y="6.6" width="16.8" height="14.8" rx="2.2" />
      <path d="M5.6 14h16.8" strokeDasharray="1.6 2.2" />
      <text
        x="14"
        y="18.6"
        textAnchor="middle"
        fontSize="11.5"
        fontWeight="700"
        fill="currentColor"
        stroke="none"
        style={{ fontFamily: "inherit" }}
      >
        {letter}
      </text>
    </Icon>
  );
}

export const LongPositionIcon = (props: IconProps) => <PositionIcon letter="L" {...props} />;
export const ShortPositionIcon = (props: IconProps) => <PositionIcon letter="S" {...props} />;

/** Rectangle: a box with a dot on each corner. */
export const RectangleIcon = ({ size = 28, ...rest }: IconProps) => (
  <Icon size={size} {...rest}>
    <rect x="7" y="9.2" width="14" height="9.6" />
    {[
      [7, 9.2],
      [21, 9.2],
      [7, 18.8],
      [21, 18.8],
    ].map(([x, y]) => (
      <circle key={`${x}-${y}`} cx={x} cy={y} r="1.5" fill="var(--ct-panel, #0f0f0f)" />
    ))}
  </Icon>
);

/** Parallel channel: two parallel slanted lines with a dashed one between. */
export const ChannelIcon = ({ size = 28, ...rest }: IconProps) => (
  <Icon size={size} {...rest}>
    <path d="M6.4 15.6L21.6 7.8" />
    <path d="M6.4 21.4L21.6 13.6" />
    <path d="M6.4 18.5L21.6 10.7" strokeDasharray="1.6 2.2" opacity="0.7" />
    <circle cx="6.4" cy="15.6" r="1.5" fill="var(--ct-panel, #0f0f0f)" />
    <circle cx="21.6" cy="7.8" r="1.5" fill="var(--ct-panel, #0f0f0f)" />
    <circle cx="14" cy="17.5" r="1.5" fill="var(--ct-panel, #0f0f0f)" />
  </Icon>
);

export const EyeIcon = ({ size = 22, ...rest }: IconProps) => (
  <Icon size={size} strokeWidth={1.3} {...rest}>
    <path d="M4.6 14s3.4-5.6 9.4-5.6S23.4 14 23.4 14s-3.4 5.6-9.4 5.6S4.6 14 4.6 14z" />
    <circle cx="14" cy="14" r="2.5" />
  </Icon>
);

export const EyeOffIcon = ({ size = 22, ...rest }: IconProps) => (
  <Icon size={size} strokeWidth={1.3} {...rest}>
    <path d="M4.6 14s3.4-5.6 9.4-5.6S23.4 14 23.4 14s-3.4 5.6-9.4 5.6S4.6 14 4.6 14z" opacity="0.55" />
    <circle cx="14" cy="14" r="2.5" opacity="0.55" />
    <path d="M6.4 21.6L21.6 6.4" />
  </Icon>
);

export const TrashIcon = ({ size = 22, ...rest }: IconProps) => (
  <Icon size={size} strokeWidth={1.3} {...rest}>
    <path d="M7.6 9.6h12.8M11.8 9.6V8.2c0-.7.5-1.2 1.2-1.2h2c.7 0 1.2.5 1.2 1.2v1.4" />
    <path d="M9 9.6l.8 10.6c.1.7.6 1.2 1.3 1.2h5.8c.7 0 1.2-.5 1.3-1.2L19 9.6" />
    <path d="M12.6 12.6v5.4M15.4 12.6v5.4" />
  </Icon>
);

/** A pencil: rename. */
export const PencilIcon = ({ size = 18, ...rest }: IconProps) => (
  <Icon size={size} strokeWidth={1.4} {...rest}>
    <path d="M8 20.5l.9-4.1 9.4-9.4a1.7 1.7 0 0 1 2.4 0l.8.8a1.7 1.7 0 0 1 0 2.4l-9.4 9.4L8 20.5z" />
    <path d="M16.6 8.8l3.2 3.2" />
  </Icon>
);

/** A wallet: the paper-trading account. */
export const WalletIcon = ({ size = 18, ...rest }: IconProps) => (
  <Icon size={size} strokeWidth={1.4} {...rest}>
    <rect x="5.5" y="8.5" width="17" height="12" rx="2.4" />
    <path d="M5.5 11.8h17" />
    <circle cx="18.2" cy="15.8" r="1.1" fill="currentColor" stroke="none" />
  </Icon>
);

/** An open book: the documentation. */
export const BookIcon = ({ size = 22, ...rest }: IconProps) => (
  <Icon size={size} strokeWidth={1.3} {...rest}>
    <path d="M14 8.6c-2.2-1.5-5.2-1.7-7.8-.9v11.6c2.6-.8 5.6-.6 7.8.9 2.2-1.5 5.2-1.7 7.8-.9V7.7c-2.6-.8-5.6-.6-7.8.9z" />
    <path d="M14 8.6v11.6" />
  </Icon>
);

/** A line that goes on to the right: the "extend right" switch of a drawing. */
export const ExtendRightIcon = ({ size = 22, ...rest }: IconProps) => (
  <Icon size={size} strokeWidth={1.4} {...rest}>
    <circle cx="7" cy="14" r="1.7" />
    <path d="M9 14h12M17.6 10.4L21.2 14l-3.6 3.6" />
  </Icon>
);

/** A closed padlock: the drawing is locked. */
export const LockIcon = ({ size = 22, ...rest }: IconProps) => (
  <Icon size={size} strokeWidth={1.3} {...rest}>
    <rect x="7.6" y="12.6" width="12.8" height="8.6" rx="1.8" />
    <path d="M10.4 12.6V10.2a3.6 3.6 0 0 1 7.2 0v2.4" />
    <circle cx="14" cy="16.9" r="1" fill="currentColor" stroke="none" />
  </Icon>
);

/** An open padlock: the drawing can be moved and removed. */
export const UnlockIcon = ({ size = 22, ...rest }: IconProps) => (
  <Icon size={size} strokeWidth={1.3} {...rest}>
    <rect x="7.6" y="12.6" width="12.8" height="8.6" rx="1.8" />
    <path d="M10.4 12.6V10.2a3.6 3.6 0 0 1 6.9-1.4" />
    <circle cx="14" cy="16.9" r="1" fill="currentColor" stroke="none" />
  </Icon>
);

/** A heart: supporting the project. */
export const HeartIcon = ({ size = 22, ...rest }: IconProps) => (
  <Icon size={size} strokeWidth={1.3} {...rest}>
    <path d="M14 21.4S6.2 16.6 6.2 11.2a4.1 4.1 0 0 1 7.8-1.8 4.1 4.1 0 0 1 7.8 1.8c0 5.4-7.8 10.2-7.8 10.2z" />
  </Icon>
);

/** An arrow rising from a tray: a newer version is there to be installed. */
export const UpdateIcon = ({ size = 22, ...rest }: IconProps) => (
  <Icon size={size} strokeWidth={1.4} {...rest}>
    <path d="M14 18.6V6.4M9.6 10.6 14 6.2l4.4 4.4" />
    <path d="M7.2 15.6v4.2a1.4 1.4 0 0 0 1.4 1.4h10.8a1.4 1.4 0 0 0 1.4-1.4v-4.2" />
  </Icon>
);
