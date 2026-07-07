/**
 * Maps a cleaning job's backend progress percentage (0–100) to a human-readable
 * stage label for the progress card. Thresholds mirror the pipeline stages the
 * worker reports; extracted from Chat.tsx so the boundaries can be tested.
 */
export function progressStageLabel(progress: number): string {
  if (progress < 20) return "Preparing data...";
  if (progress < 55) return "Applying cleaning steps...";
  if (progress < 80) return "Verifying results & fixing issues...";
  return "Finalizing cleaned file...";
}
