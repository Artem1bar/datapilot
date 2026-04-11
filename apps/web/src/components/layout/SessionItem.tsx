import { useState } from "react";
import { Pin, Pencil, Trash2, Check, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { Session } from "@/types";

interface SessionItemProps {
  session: Session;
  isActive: boolean;
  sidebarOpen: boolean;
  onClick: () => void;
  onRename: (title: string) => void;
  onPin: () => void;
  onDelete: () => void;
}

export function SessionItem({
  session,
  isActive,
  sidebarOpen,
  onClick,
  onRename,
  onPin,
  onDelete,
}: SessionItemProps) {
  const [editing, setEditing] = useState(false);
  const [editValue, setEditValue] = useState(session.title);
  const [deleteOpen, setDeleteOpen] = useState(false);

  const handleRename = () => {
    const trimmed = editValue.trim();
    if (trimmed && trimmed !== session.title) {
      onRename(trimmed);
    }
    setEditing(false);
  };

  const timeAgo = formatRelative(session.updatedAt);

  if (!sidebarOpen) {
    return (
      <button
        type="button"
        onClick={onClick}
        className={cn(
          "flex h-9 w-9 items-center justify-center rounded-lg text-[11px] font-medium transition-all duration-150",
          isActive
            ? "bg-brand-100 text-brand-600"
            : "text-ink-secondary hover:bg-[var(--surface-inset)] hover:text-ink",
        )}
        title={session.title}
      >
        {session.title.slice(0, 2).toUpperCase()}
      </button>
    );
  }

  return (
    <>
      <div
        role="button"
        tabIndex={0}
        onClick={editing ? undefined : onClick}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !editing) onClick();
        }}
        className={cn(
          "group relative flex items-center gap-2 rounded-lg px-3 py-2 text-[13px] transition-all duration-150 cursor-pointer",
          isActive
            ? "bg-brand-100 text-brand-600 shadow-[inset_0_0_0_1px_var(--brand-300)]"
            : "text-ink-secondary hover:bg-[var(--surface-inset)] hover:text-ink",
        )}
      >
        {/* Pin indicator */}
        {session.pinned && (
          <Pin className="h-3 w-3 shrink-0 rotate-45 text-gold-500" />
        )}

        {/* Title & subtitle */}
        {editing ? (
          <form
            className="flex flex-1 items-center gap-1"
            onSubmit={(e) => { e.preventDefault(); handleRename(); }}
          >
            <Input
              value={editValue}
              onChange={(e) => setEditValue(e.target.value)}
              className="h-6 text-[12px]"
              autoFocus
            />
            <Button type="submit" variant="ghost" size="icon" className="h-5 w-5">
              <Check className="h-3 w-3" />
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="h-5 w-5"
              onClick={() => setEditing(false)}
            >
              <X className="h-3 w-3" />
            </Button>
          </form>
        ) : (
          <div className="flex-1 min-w-0">
            <p className="truncate font-medium">{session.title}</p>
            <p className="truncate text-[11px] text-ink-muted">
              {session.subtitle || timeAgo}
            </p>
          </div>
        )}

        {/* Hover actions */}
        {!editing && (
          <div className="absolute right-2 top-1/2 -translate-y-1/2 flex gap-0.5 opacity-0 transition-opacity group-hover:opacity-100">
            <Button
              variant="ghost"
              size="icon"
              className="h-5 w-5 text-ink-muted hover:text-gold-600"
              onClick={(e) => { e.stopPropagation(); onPin(); }}
              title={session.pinned ? "Unpin" : "Pin"}
            >
              <Pin className={cn("h-3 w-3", session.pinned && "rotate-45 fill-gold-500")} />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className="h-5 w-5 text-ink-muted hover:text-ink"
              onClick={(e) => { e.stopPropagation(); setEditing(true); setEditValue(session.title); }}
              title="Rename"
            >
              <Pencil className="h-3 w-3" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className="h-5 w-5 text-ink-muted hover:text-coral-600"
              onClick={(e) => { e.stopPropagation(); setDeleteOpen(true); }}
              title="Delete"
            >
              <Trash2 className="h-3 w-3" />
            </Button>
          </div>
        )}
      </div>

      {/* Delete confirmation dialog */}
      <Dialog open={deleteOpen} onOpenChange={setDeleteOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete session?</DialogTitle>
            <DialogDescription>
              &ldquo;{session.title}&rdquo; and its messages will be permanently removed.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteOpen(false)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={() => { setDeleteOpen(false); onDelete(); }}
            >
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

/* ── Relative time helper ───────────────────────────────────────────────── */

function formatRelative(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const minutes = Math.floor(diff / 60_000);
  if (minutes < 1) return "Just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d ago`;
  return new Date(iso).toLocaleDateString();
}
