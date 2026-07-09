import type { ReactNode } from "react";
import { ClerkProvider, SignedIn, SignedOut, SignIn } from "@clerk/clerk-react";

const publishableKey = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY;

function SignInScreen() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-[var(--surface-page)] p-6">
      <SignIn routing="hash" />
    </div>
  );
}

/**
 * Gates the app behind Clerk auth when a publishable key is configured.
 * With no key (local dev), it renders children directly — the backend's
 * DEV_AUTH_BYPASS handles auth in that mode.
 */
export function AuthGate({ children }: { children: ReactNode }) {
  if (!publishableKey) {
    return <>{children}</>;
  }
  return (
    <ClerkProvider publishableKey={publishableKey}>
      <SignedIn>{children}</SignedIn>
      <SignedOut>
        <SignInScreen />
      </SignedOut>
    </ClerkProvider>
  );
}
