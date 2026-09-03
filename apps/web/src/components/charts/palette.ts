/** LSU brand palette — purple-dominant with gold accents. Shared by every chart. */
export const BRAND_PURPLE = "#461D7C";
export const BRAND_GOLD = "#FDD023";

/** Series colors for bar, line and pie charts, in brand order. */
export const CHART_COLORS = [
  "#461D7C", // LSU purple
  "#FDD023", // LSU gold
  "#6B32A8", // lighter purple
  "#E8B820", // deeper gold
  "#8B5CF6", // violet
  "#F59E0B", // amber
  "#7C3AED", // indigo-purple
  "#D97706", // warm orange
] as const;

/**
 * Hues for colored groups on a scatter plot. Chosen to be distinguishable
 * from each other at 6px, and none of them the gold of the fitted line, so
 * the line is never mistaken for a group. Twelve entries: the API refuses a
 * color column with more levels than a legend can hold.
 */
export const GROUP_COLORS = [
  "#461D7C", // LSU purple
  "#D97706", // amber
  "#0F766E", // teal
  "#B91C1C", // red
  "#1D4ED8", // blue
  "#7C3AED", // violet
  "#65A30D", // green
  "#DB2777", // pink
  "#0891B2", // cyan
  "#92400E", // brown
  "#4B5563", // slate
  "#CA8A04", // dark gold
] as const;
