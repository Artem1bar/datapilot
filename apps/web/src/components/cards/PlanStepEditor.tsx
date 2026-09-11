import { Input } from "@/components/ui/input";
import {
  coerceParam,
  formatIntegerList,
  formatMapping,
  type EditableStep,
  type OperationSpec,
  type ParamSpec,
} from "@/lib/plan-editor";

interface Props {
  step: EditableStep;
  spec: OperationSpec;
  /** Real column names from the dataset profile, for the column pickers. */
  columns: readonly string[];
  onColumnChange: (column: string | null) => void;
  onParamChange: (name: string, value: unknown) => void;
  onDescriptionChange: (description: string) => void;
}

const FIELD =
  "w-full rounded-md border border-[var(--line)] bg-[var(--surface-primary)] px-2 py-1 text-[12px] text-ink " +
  "focus:outline-none focus:ring-1 focus:ring-brand-500";

function FieldShell({
  label,
  help,
  required,
  children,
}: {
  label: string;
  help?: string;
  required?: boolean;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-0.5 block text-[11px] font-medium text-ink-secondary">
        {label}
        {required && <span className="ml-0.5 text-rose-600">*</span>}
      </span>
      {children}
      {help && <span className="mt-0.5 block text-[10px] text-ink-muted">{help}</span>}
    </label>
  );
}

/** Picks one of the dataset's real columns — a typo is not possible here. */
function ColumnSelect({
  value,
  columns,
  onChange,
  placeholder = "Choose a column…",
}: {
  value: string | null;
  columns: readonly string[];
  onChange: (value: string | null) => void;
  placeholder?: string;
}) {
  // A plan can name a column the profile does not list (a column an earlier
  // step creates). Keep it as an option rather than silently resetting it.
  const options = value && !columns.includes(value) ? [value, ...columns] : columns;
  return (
    <select
      className={FIELD}
      value={value ?? ""}
      onChange={(event) => onChange(event.target.value || null)}
    >
      <option value="">{placeholder}</option>
      {options.map((column) => (
        <option key={column} value={column}>
          {column}
        </option>
      ))}
    </select>
  );
}

function ParamField({
  param,
  value,
  columns,
  onChange,
}: {
  param: ParamSpec;
  value: unknown;
  columns: readonly string[];
  onChange: (value: unknown) => void;
}) {
  const commit = (raw: unknown) => onChange(coerceParam(param, raw));

  switch (param.kind) {
    case "enum":
      return (
        <select
          className={FIELD}
          value={typeof value === "string" ? value : ""}
          onChange={(event) => commit(event.target.value)}
        >
          <option value="">{param.required ? "Choose…" : "None"}</option>
          {param.choices.map((choice) => (
            <option key={choice} value={choice}>
              {choice}
            </option>
          ))}
        </select>
      );

    case "column":
      return (
        <ColumnSelect
          value={typeof value === "string" ? value : null}
          columns={columns}
          onChange={(next) => onChange(next ?? undefined)}
        />
      );

    case "column_list":
      return (
        <select
          className={FIELD}
          multiple
          size={Math.min(4, Math.max(2, columns.length))}
          value={Array.isArray(value) ? (value as string[]) : []}
          onChange={(event) =>
            commit(Array.from(event.target.selectedOptions, (option) => option.value))
          }
        >
          {columns.map((column) => (
            <option key={column} value={column}>
              {column}
            </option>
          ))}
        </select>
      );

    case "mapping":
      return (
        <textarea
          className={`${FIELD} font-mono`}
          rows={3}
          placeholder="NYC = New York"
          defaultValue={formatMapping(value)}
          onBlur={(event) => commit(event.target.value)}
        />
      );

    case "integer_list":
      return (
        <Input
          className="h-7 text-[12px]"
          placeholder="0, 1, 4"
          defaultValue={formatIntegerList(value)}
          onBlur={(event) => commit(event.target.value)}
        />
      );

    case "number":
    case "integer":
      return (
        <Input
          className="h-7 text-[12px]"
          type="number"
          step={param.kind === "integer" ? 1 : "any"}
          defaultValue={typeof value === "number" ? String(value) : ""}
          onBlur={(event) => commit(event.target.value)}
        />
      );

    default:
      return (
        <Input
          className="h-7 text-[12px]"
          defaultValue={typeof value === "string" ? value : ""}
          onBlur={(event) => commit(event.target.value)}
        />
      );
  }
}

/**
 * The expanded form for one step: what it targets, what it does, and how the
 * user described it.
 *
 * Text and number fields commit on blur rather than on every keystroke, so a
 * half-typed number never briefly becomes the applied value and the validation
 * message does not flicker while the user is mid-word.
 */
export function PlanStepEditor({
  step,
  spec,
  columns,
  onColumnChange,
  onParamChange,
  onDescriptionChange,
}: Props) {
  const params = step.params ?? {};

  return (
    <div className="mt-2 space-y-2.5 rounded-lg bg-[var(--surface-inset)] p-3">
      <p className="text-[11px] leading-relaxed text-ink-muted">{spec.summary}</p>

      <div className="grid gap-2.5 sm:grid-cols-2">
        {spec.requiresColumn && (
          <FieldShell label="Target column" required>
            <ColumnSelect value={step.column} columns={columns} onChange={onColumnChange} />
          </FieldShell>
        )}

        {spec.params.map((param) => (
          <FieldShell
            key={param.name}
            label={param.label}
            help={param.help}
            required={param.required}
          >
            <ParamField
              param={param}
              value={params[param.name]}
              columns={columns}
              onChange={(value) => onParamChange(param.name, value)}
            />
          </FieldShell>
        ))}
      </div>

      <FieldShell label="Description" help="What this step will say in the audit trail.">
        <Input
          className="h-7 text-[12px]"
          defaultValue={step.description}
          onBlur={(event) => onDescriptionChange(event.target.value)}
        />
      </FieldShell>
    </div>
  );
}
