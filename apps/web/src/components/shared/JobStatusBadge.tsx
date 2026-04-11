import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { JobStatus } from "@/types";

const statusStyles: Record<JobStatus, string> = {
  pending: "bg-gray-200 text-gray-700 dark:bg-gray-700 dark:text-gray-200",
  running: "bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300",
  completed:
    "bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300",
  failed: "bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300",
};

interface JobStatusBadgeProps {
  status: JobStatus;
  className?: string;
}

export function JobStatusBadge({ status, className }: JobStatusBadgeProps) {
  return (
    <Badge
      variant="secondary"
      className={cn(
        "capitalize",
        statusStyles[status],
        className,
      )}
    >
      {status}
    </Badge>
  );
}
