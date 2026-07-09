/**
 * Client-side upload validation. Mirrors the backend caps (`MAX_UPLOAD_BYTES`
 * and the CSV/Excel content check) so an oversize or wrong-type file is
 * rejected with a clear message *before* it round-trips to the server. The
 * `accept` attribute on the file input is only a hint — drag-drop, paste, and
 * "All Files" selection all bypass it — so this is the real guard.
 */

/** Max upload size in bytes — mirrors the backend `MAX_UPLOAD_BYTES` (50 MB). */
export const MAX_UPLOAD_BYTES = 50 * 1024 * 1024;

/** Human-readable form of {@link MAX_UPLOAD_BYTES} for UI copy. */
export const MAX_UPLOAD_LABEL = "50 MB";

/** Extensions we accept: CSV/TSV plus Excel. */
export const ACCEPTED_EXTENSIONS = [".csv", ".tsv", ".xls", ".xlsx"] as const;

export type UploadValidation = { ok: true } | { ok: false; reason: string };

/** Lowercased extension including the dot (".csv"), or "" when there is none. */
function extensionOf(filename: string): string {
  const dot = filename.lastIndexOf(".");
  return dot === -1 ? "" : filename.slice(dot).toLowerCase();
}

/** Compact human size, e.g. 620 B, 1.4 MB, 2.1 GB. */
export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  // One decimal, but drop a trailing ".0".
  const rounded = Math.round(value * 10) / 10;
  return `${rounded % 1 === 0 ? rounded.toFixed(0) : rounded.toFixed(1)} ${units[unit]}`;
}

/**
 * Validate a file against the type and size caps. Returns a discriminated
 * result so callers can surface `reason` directly to the user.
 */
export function validateUploadFile(
  file: File,
  maxBytes: number = MAX_UPLOAD_BYTES,
): UploadValidation {
  const ext = extensionOf(file.name);
  if (!ACCEPTED_EXTENSIONS.includes(ext as (typeof ACCEPTED_EXTENSIONS)[number])) {
    const shown = ext || `"${file.name}"`;
    return {
      ok: false,
      reason: `Unsupported file type ${shown}. Upload a CSV or Excel file (${ACCEPTED_EXTENSIONS.join(", ")}).`,
    };
  }
  if (file.size === 0) {
    return { ok: false, reason: "That file is empty — nothing to upload." };
  }
  if (file.size > maxBytes) {
    return {
      ok: false,
      reason: `That file is ${formatBytes(file.size)}, over the ${MAX_UPLOAD_LABEL} limit. Try a smaller file or split it up.`,
    };
  }
  return { ok: true };
}
