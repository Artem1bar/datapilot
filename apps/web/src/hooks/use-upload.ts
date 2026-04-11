import { useState, useCallback } from "react";
import { api } from "@/lib/api";
import type { UploadUrlResponse, JobResponse } from "@/types";

interface UseUploadOptions {
  onSuccess?: (datasetId: string, jobId: string) => void;
  onError?: (error: Error) => void;
}

export function useUpload({ onSuccess, onError }: UseUploadOptions = {}) {
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);

  const upload = useCallback(
    async (file: File) => {
      setUploading(true);
      setProgress(0);

      try {
        // 1. Request a presigned upload URL from the backend
        const { upload_url, dataset_id } = await api
          .post("datasets/upload-url", {
            json: {
              filename: file.name,
              content_type: file.type || "text/csv",
              file_size_bytes: file.size,
            },
          })
          .json<UploadUrlResponse>();

        // 2. Upload the file directly to the presigned URL (MinIO / R2)
        await new Promise<void>((resolve, reject) => {
          const xhr = new XMLHttpRequest();
          xhr.open("PUT", upload_url);
          xhr.setRequestHeader("Content-Type", file.type || "text/csv");

          xhr.upload.addEventListener("progress", (e) => {
            if (e.lengthComputable) {
              setProgress(Math.round((e.loaded / e.total) * 100));
            }
          });

          xhr.addEventListener("load", () => {
            if (xhr.status >= 200 && xhr.status < 300) {
              resolve();
            } else {
              reject(
                new Error(`Upload failed with status ${String(xhr.status)}`),
              );
            }
          });

          xhr.addEventListener("error", () => reject(new Error("Upload failed")));
          xhr.send(file);
        });

        // 3. Confirm the upload with the backend
        const job = await api
          .post(`datasets/${dataset_id}/confirm`, {
            json: { filename: file.name },
          })
          .json<JobResponse>();

        setProgress(100);
        onSuccess?.(dataset_id, job.id);
      } catch (err) {
        const error = err instanceof Error ? err : new Error("Upload failed");
        onError?.(error);
      } finally {
        setUploading(false);
      }
    },
    [onSuccess, onError],
  );

  return { upload, uploading, progress };
}
