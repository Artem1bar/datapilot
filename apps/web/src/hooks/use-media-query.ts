import { useState, useEffect } from "react";

export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() =>
    typeof window !== "undefined" ? window.matchMedia(query).matches : false,
  );

  useEffect(() => {
    const mql = window.matchMedia(query);
    const handler = (e: MediaQueryListEvent) => setMatches(e.matches);
    mql.addEventListener("change", handler);
    // Sync state when query prop changes between renders
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setMatches(mql.matches);
    return () => mql.removeEventListener("change", handler);
  }, [query]);

  return matches;
}
