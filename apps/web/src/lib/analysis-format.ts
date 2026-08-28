/**
 * Rendering rules for computed statistics.
 *
 * The backend reports a statistic it could not compute as `null` rather than
 * omitting the key, so every formatter here has to answer the question "what
 * does a reader see when there is no number". The answer is an em dash — never
 * the string "null", never a zero, and never a value invented to fill the gap.
 *
 * The second rule is that small magnitudes keep their significant figures.
 * `analysis_stats.json_safe` deliberately preserves p-values below 1e-4 rather
 * than rounding them to 0.0, because "p = 0" claims a certainty no test can
 * support; formatting them to four decimal places on the way to the screen
 * would throw away exactly what the backend went to the trouble of keeping.
 */

/** What a missing statistic looks like. */
export const NOT_COMPUTED = "—";

/** Below this magnitude, fixed decimals destroy significant digits. */
const EXPONENTIAL_BELOW = 1e-4;

/** Above this magnitude, fixed decimals are noise; use exponent notation. */
const EXPONENTIAL_ABOVE = 1e9;

function isRenderable(value: number | null | undefined): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

/**
 * A statistic, at four significant decimals, or the em dash when there is none.
 *
 * Trailing zeros are dropped: an estimate of exactly 2 reads as "2", not
 * "2.0000", which would imply a precision the rounding does not carry.
 */
export function formatStatistic(
  value: number | null | undefined,
  digits = 4,
): string {
  if (!isRenderable(value)) return NOT_COMPUTED;
  const magnitude = Math.abs(value);
  if (
    magnitude !== 0 &&
    (magnitude < EXPONENTIAL_BELOW || magnitude >= EXPONENTIAL_ABOVE)
  ) {
    return value.toExponential(2);
  }
  return Number(value.toFixed(digits)).toString();
}

/** A p-value. Never rendered as 0 — see the module note. */
export function formatPValue(value: number | null | undefined): string {
  return formatStatistic(value);
}

/** A count, grouped for readability. Fractional counts keep one decimal. */
export function formatCount(value: number | null | undefined): string {
  if (!isRenderable(value)) return NOT_COMPUTED;
  return Number.isInteger(value)
    ? value.toLocaleString()
    : value.toLocaleString(undefined, { maximumFractionDigits: 1 });
}

/** A confidence or prediction interval, or the em dash if either bound is gone. */
export function formatInterval(
  low: number | null | undefined,
  high: number | null | undefined,
  digits = 4,
): string {
  if (!isRenderable(low) || !isRenderable(high)) return NOT_COMPUTED;
  return `[${formatStatistic(low, digits)}, ${formatStatistic(high, digits)}]`;
}

/** A confidence level as a percentage — 0.95 becomes "95%". */
export function formatLevel(level: number | null | undefined): string {
  return `${Math.round((isRenderable(level) ? level : 0.95) * 100)}%`;
}

/**
 * Whether an estimate is significant at the conventional 5% level.
 *
 * Returns null when there is no p-value, which the caller must render as
 * "unknown" rather than as "not significant" — the two are different claims.
 */
export function isSignificant(
  pValue: number | null | undefined,
): boolean | null {
  return isRenderable(pValue) ? pValue < 0.05 : null;
}
