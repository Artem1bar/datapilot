import { describe, it, expect } from "vitest";
import {
  validateUploadFile,
  formatBytes,
  MAX_UPLOAD_BYTES,
  ACCEPTED_EXTENSIONS,
} from "./upload";

/** Build a File with an arbitrary reported size without allocating it. */
function fileOf(name: string, size = 10): File {
  const file = new File(["content"], name);
  Object.defineProperty(file, "size", { value: size });
  return file;
}

describe("validateUploadFile", () => {
  it.each(ACCEPTED_EXTENSIONS)("accepts %s", (ext) => {
    expect(validateUploadFile(fileOf(`data${ext}`))).toEqual({ ok: true });
  });

  it("is case-insensitive on the extension", () => {
    expect(validateUploadFile(fileOf("DATA.CSV"))).toEqual({ ok: true });
    expect(validateUploadFile(fileOf("Report.XlsX"))).toEqual({ ok: true });
  });

  it("rejects unsupported extensions with a helpful reason", () => {
    const result = validateUploadFile(fileOf("resume.pdf"));
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.reason).toContain(".pdf");
      expect(result.reason).toContain("CSV or Excel");
    }
  });

  it("rejects a file with no extension", () => {
    const result = validateUploadFile(fileOf("noextension"));
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toContain("noextension");
  });

  it("rejects an empty file", () => {
    const result = validateUploadFile(fileOf("empty.csv", 0));
    expect(result).toEqual({ ok: false, reason: expect.stringContaining("empty") });
  });

  it("rejects a file over the size cap and names the size + limit", () => {
    const result = validateUploadFile(fileOf("big.csv", 100), 50);
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.reason).toContain("50 MB");
      expect(result.reason).toContain("100 B");
    }
  });

  it("accepts a file exactly at the cap", () => {
    expect(validateUploadFile(fileOf("edge.csv", 50), 50)).toEqual({ ok: true });
  });

  it("defaults the cap to MAX_UPLOAD_BYTES (50 MB)", () => {
    expect(validateUploadFile(fileOf("ok.csv", MAX_UPLOAD_BYTES))).toEqual({ ok: true });
    expect(validateUploadFile(fileOf("too-big.csv", MAX_UPLOAD_BYTES + 1)).ok).toBe(false);
  });
});

describe("formatBytes", () => {
  it.each([
    [0, "0 B"],
    [620, "620 B"],
    [1024, "1 KB"],
    [1536, "1.5 KB"],
    [1024 * 1024, "1 MB"],
    [Math.round(2.1 * 1024 * 1024), "2.1 MB"],
    [1024 * 1024 * 1024, "1 GB"],
  ])("formats %i bytes as %s", (bytes, label) => {
    expect(formatBytes(bytes)).toBe(label);
  });
});
