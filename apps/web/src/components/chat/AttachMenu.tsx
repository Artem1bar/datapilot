import { useRef, useState } from "react";
import { Plus, Upload, ClipboardPaste, BookOpen, Trash2, Loader2 } from "lucide-react";
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
import { api } from "@/lib/api";
import { ACCEPTED_EXTENSIONS, MAX_UPLOAD_LABEL } from "@/lib/upload";

// Single source for accepted types (shared with the client-side validator).
const ACCEPTED_TYPES = ACCEPTED_EXTENSIONS.join(",");

export interface RecipeSummary {
  id: string;
  name: string;
  description: string | null;
  steps_json: { steps?: unknown[] };
  created_at: string;
}

interface AttachMenuProps {
  onFileAttach: (file: File) => void;
  onTablePaste: (text: string) => void;
  /** Called with the chosen recipe id; only offered when a dataset is attached. */
  onApplyRecipe?: (recipeId: string) => void;
  hasDataset?: boolean;
  disabled?: boolean;
}

export function AttachMenu({
  onFileAttach,
  onTablePaste,
  onApplyRecipe,
  hasDataset = false,
  disabled,
}: AttachMenuProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [pasteOpen, setPasteOpen] = useState(false);
  const [pasteValue, setPasteValue] = useState("");
  const [recipesOpen, setRecipesOpen] = useState(false);
  const [recipes, setRecipes] = useState<RecipeSummary[] | null>(null);
  const [recipesError, setRecipesError] = useState<string | null>(null);

  const openRecipes = () => {
    setRecipesOpen(true);
    setRecipes(null);
    setRecipesError(null);
    api
      .get("recipes/")
      .json<RecipeSummary[]>()
      .then(setRecipes)
      .catch((err: unknown) => {
        setRecipesError(err instanceof Error ? err.message : "Couldn't load recipes");
      });
  };

  const deleteRecipe = (id: string) => {
    setRecipes((prev) => (prev ? prev.filter((r) => r.id !== id) : prev));
    api.delete(`recipes/${id}`).catch(() => {
      // Restore on failure by refetching.
      api.get("recipes/").json<RecipeSummary[]>().then(setRecipes).catch(() => undefined);
    });
  };

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
            aria-label="Open attach menu"
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
          {onApplyRecipe && (
            <DropdownMenuItem disabled={!hasDataset} onClick={openRecipes}>
              <BookOpen className="mr-2 h-4 w-4" />
              <span className="flex flex-col">
                <span>Apply a recipe</span>
                {!hasDataset && (
                  <span className="text-[11px] text-ink-tertiary">Attach a dataset first</span>
                )}
              </span>
            </DropdownMenuItem>
          )}
        </DropdownMenuContent>
      </DropdownMenu>

      {/* Recipe picker dialog */}
      <Dialog open={recipesOpen} onOpenChange={setRecipesOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Apply a recipe</DialogTitle>
            <DialogDescription>
              Run a saved cleaning plan against the current dataset. Steps are validated against
              its columns before anything runs.
            </DialogDescription>
          </DialogHeader>
          {recipesError ? (
            <p className="text-[13px] text-red-600">{recipesError}</p>
          ) : recipes === null ? (
            <div className="flex items-center gap-2 py-4 text-[13px] text-ink-muted">
              <Loader2 className="h-4 w-4 animate-spin" />
              Loading recipes...
            </div>
          ) : recipes.length === 0 ? (
            <p className="py-4 text-[13px] text-ink-muted">
              No recipes yet — after a cleaning finishes, use &ldquo;Save as recipe&rdquo; on the
              results card.
            </p>
          ) : (
            <ul className="max-h-72 space-y-2 overflow-y-auto">
              {recipes.map((recipe) => (
                <li
                  key={recipe.id}
                  className="flex items-center gap-3 rounded-lg border border-[var(--line)] px-3 py-2"
                >
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-[13px] font-medium text-ink">{recipe.name}</p>
                    <p className="truncate text-[12px] text-ink-muted">
                      {recipe.steps_json?.steps?.length ?? 0} steps
                      {recipe.description ? ` — ${recipe.description}` : ""}
                    </p>
                  </div>
                  <Button
                    size="sm"
                    className="bg-brand-600 text-white hover:bg-brand-700"
                    onClick={() => {
                      setRecipesOpen(false);
                      onApplyRecipe?.(recipe.id);
                    }}
                  >
                    Apply
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-8 w-8 text-ink-muted hover:text-red-600"
                    aria-label={`Delete recipe ${recipe.name}`}
                    onClick={() => deleteRecipe(recipe.id)}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </DialogContent>
      </Dialog>

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
