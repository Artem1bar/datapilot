import { Routes, Route, Navigate } from "react-router-dom";
import { ChatLayout } from "@/components/layout/ChatLayout";
import Chat from "@/pages/Chat";
import CleanedDatasets from "@/pages/CleanedDatasets";
import Settings from "@/pages/Settings";

function NotFoundPage() {
  return (
    <div className="flex h-screen items-center justify-center font-sans">
      <div className="text-center">
        <h1 className="font-sans text-4xl font-bold text-ink">
          404
        </h1>
        <p className="mt-2 text-ink-secondary">Page not found</p>
      </div>
    </div>
  );
}

export default function App() {
  return (
    <Routes>
      {/* Redirect root to chat */}
      <Route path="/" element={<Navigate to="/app" replace />} />

      {/* App routes (chat-first layout) */}
      <Route path="/app" element={<ChatLayout />}>
        <Route index element={<Chat />} />
        <Route path="cleaned-datasets" element={<CleanedDatasets />} />
        <Route path="settings" element={<Settings />} />
      </Route>

      {/* Legacy routes redirect to chat */}
      <Route path="/app/dashboard" element={<Navigate to="/app" replace />} />
      <Route path="/app/upload" element={<Navigate to="/app" replace />} />

      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  );
}
