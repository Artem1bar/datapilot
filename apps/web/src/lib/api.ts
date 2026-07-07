import ky from "ky";

/**
 * In development: Vite proxy forwards /api → localhost:8001
 * In production:  VITE_API_URL points to the deployed API
 */
const apiBase = import.meta.env.VITE_API_URL
  ? `${import.meta.env.VITE_API_URL}/api/v1`
  : "/api/v1";

/** Minimal shape of the Clerk singleton exposed on window once ClerkProvider mounts. */
interface ClerkGlobal {
  session?: { getToken?: () => Promise<string | null> };
}

export const api = ky.create({
  prefixUrl: apiBase,
  timeout: 180_000, // 3 min — AI calls can take 30-60s
  retry: {
    limit: 1,
    methods: ["get"],
    statusCodes: [408, 429],
    backoffLimit: 2000,
  },
  hooks: {
    beforeRequest: [
      async (request) => {
        // Attach the Clerk session token when Clerk is active (production auth).
        // In dev without Clerk this is a no-op; the backend uses DEV_AUTH_BYPASS.
        const clerk = (window as unknown as { Clerk?: ClerkGlobal }).Clerk;
        const token = await clerk?.session?.getToken?.();
        if (token) {
          request.headers.set("Authorization", `Bearer ${token}`);
        }
      },
    ],
    beforeError: [
      async (error) => {
        const { response } = error;
        if (!response) {
          error.message =
            "Could not reach the server. Please check that the API is running.";
          return error;
        }
        try {
          const body = await response.clone().json() as { detail?: string };
          if (body?.detail) {
            error.message = body.detail;
          }
        } catch {
          // ignore parse errors — use default message
        }
        return error;
      },
    ],
  },
});
