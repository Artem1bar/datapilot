import { useRef, useState } from "react";
import { Plus, Upload, ClipboardPaste } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ACCEPTED_EXTENSIONS, MAX_UPLOAD_LABEL } from "@/lib/upload";

// Single source for accepted types (shared with the client-side validator).
const ACCEPTED_TYPES = ACCEPTED_EXTENSIONS.join(",");

interface AttachMenuProps {
  onFileAttach: (file: File) => void;
  onTablePaste: (text: string) => void;
  disabled?: boolean;
}

export function AttachMenu({ onFileAttach, onTablePaste, disabled }: AttachMenuProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [pasteOpen, setPasteOpen] = useState(false);
  const [pasteValue, setPasteValue] = useState("");

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      onFileAttach(file);
      e.target.value = "";
    }
  };

  const handlePasteSubmit = () => {
    const trimmed = pasteValue.trim();
    if (trimmed) {
      onTablePaste(trimmed);
      setPasteValue("");
      setPasteOpen(false);
    }
  };

  return (
    <>
      <input
        ref={fileInputRef}
        type="file"
        accept={ACCEPTED_TYPES}
        className="hidden"
        onChange={handleFileChange}
      />

      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            variant="ghost"
            size="icon"
            className="h-9 w-9 shrink-0 text-ink-tertiary hover:text-ink hover:bg-[var(--surface-inset)] transition-all duration-150"
            disabled={disabled}
          >
            <Plus className="h-4 w-4" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="w-48">
          <DropdownMenuItem onClick={() => fileInputRef.current?.click()}>
            <Upload className="mr-2 h-4 w-4" />
            <span className="flex flex-col">
              <span>Upload CSV or Excel</span>
              <span className="text-[11px] text-ink-tertiary">Up to {MAX_UPLOAD_LABEL}</span>
            </span>
          </DropdownMenuItem>
          <DropdownMenuItem onClick={() => setPasteOpen(true)}>
            <ClipboardPaste className="mr-2 h-4 w-4" />
            Paste table
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      {/* Paste table dialog */}
      <Dialog open={pasteOpen} onOpenChange={setPasteOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Paste table data</DialogTitle>
            <DialogDescription>
              Paste tab-separated or comma-separated data below.
            </DialogDescription>
          </DialogHeader>
          <Textarea
            placeholder="Name\tAge\tCity\nJohn\t30\tNew York\nJane\t25\tLondon"
            value={pasteValue}
            onChange={(e) => setPasteValue(e.target.value)}
            className="min-h-[120px] font-mono text-[12px]"
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setPasteOpen(false)}>
              Cancel
            </Button>
            <Button
              className="bg-brand-600 text-white hover:bg-brand-700"
              onClick={handlePasteSubmit}
              disabled={!pasteValue.trim()}
            >
              Add data
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
