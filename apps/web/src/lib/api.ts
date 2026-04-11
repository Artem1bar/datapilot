import ky from "ky";

/**
 * In development: Vite proxy forwards /api → localhost:8001
 * In production:  VITE_API_URL points to the deployed API
 */
const apiBase = import.meta.env.VITE_API_URL
  ? `${import.meta.env.VITE_API_URL}/api/v1`
  : "/api/v1";

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
