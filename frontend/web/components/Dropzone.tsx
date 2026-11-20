import { useRef, useState } from "react";
import { FileUp } from "lucide-react";
import { cx } from "../lib/util";
import { Spinner } from "./ui";

export function Dropzone({
  onFiles,
  busy,
  compact = false,
  hint = "PDF or DOCX, up to 10 MB each",
}: {
  onFiles: (files: File[]) => void;
  busy?: boolean;
  compact?: boolean;
  hint?: string;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const depth = useRef(0);

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => !busy && input.current?.click()}
      onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && !busy && input.current?.click()}
      onDragEnter={(e) => {
        e.preventDefault();
        depth.current += 1;
        setOver(true);
      }}
      onDragOver={(e) => e.preventDefault()}
      onDragLeave={() => {
        depth.current -= 1;
        if (depth.current <= 0) setOver(false);
      }}
      onDrop={(e) => {
        e.preventDefault();
        depth.current = 0;
        setOver(false);
        const files = Array.from(e.dataTransfer.files);
        if (files.length && !busy) onFiles(files);
      }}
      className={cx(
        "group flex cursor-pointer flex-col items-center justify-center rounded-lg border border-dashed text-center transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/60",
        compact ? "gap-1 px-4 py-6" : "gap-2 px-6 py-12",
        over
          ? "border-violet-500 bg-violet-50/60 dark:border-violet-400 dark:bg-violet-500/10"
          : "border-zinc-300 hover:border-zinc-500 dark:border-zinc-700 dark:hover:border-zinc-500",
      )}
    >
      <input
        ref={input}
        type="file"
        multiple
        accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        className="hidden"
        onChange={(e) => {
          const files = Array.from(e.target.files ?? []);
          e.target.value = "";
          if (files.length) onFiles(files);
        }}
      />
      <div className="text-zinc-400 transition-colors duration-150 group-hover:text-violet-600 dark:text-zinc-500 dark:group-hover:text-violet-400">
        {busy ? <Spinner className="size-5 text-violet-500" /> : <FileUp className="size-5" strokeWidth={1.5} />}
      </div>
      <p className="mt-1 text-sm font-medium text-zinc-800 dark:text-zinc-200">
        {busy ? "Uploading…" : over ? "Drop to upload" : "Drop resumes here, or click to browse"}
      </p>
      <p className="text-xs text-zinc-500 dark:text-zinc-400">{hint}</p>
    </div>
  );
}
