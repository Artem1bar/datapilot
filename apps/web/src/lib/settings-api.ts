import { api } from "./api";

/** Mirrors the backend app.schemas.settings.UserPreferences model. */
export interface UserPreferences {
  cleaning_aggressiveness: "conservative" | "standard" | "aggressive";
  outlier_method: "mad" | "iqr" | "none";
  outlier_threshold: number;
  cap_strategy: "off" | "auto" | "manual";
  null_fill_default: "none" | "mean" | "median" | "mode" | "zero";
  dedup_default: boolean;
  domain: "auto" | "survey" | "generic";
  custom_instructions: string;
  ai_sample_size: number;
  max_remediation_rounds: number;
  review_first: boolean;
  cleaning_model: string | null;
  verification_model: string | null;
}

export function getSettings(): Promise<UserPreferences> {
  return api.get("settings/").json<UserPreferences>();
}

export function updateSettings(patch: Partial<UserPreferences>): Promise<UserPreferences> {
  return api.put("settings/", { json: patch }).json<UserPreferences>();
}
