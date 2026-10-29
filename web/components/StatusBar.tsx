import { fmtUpdated } from "@/lib/format";
import type { SourceStatus } from "@/lib/types";

export function StatusBar({ generatedAt, season, model, sources }: { generatedAt: string; season: string; model: string; sources: SourceStatus[] }) {
  const failing = sources.filter((s) => s.last_error_at && (!s.last_ok_at || s.last_error_at > s.last_ok_at));
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted">
      <span>
        Data last updated <time dateTime={generatedAt} className="font-medium text-ink-2">{fmtUpdated(generatedAt)}</time>
      </span>
      <span>Season {season}</span>
      <span>Model {model}</span>
      {failing.length > 0 && (
        <span className="text-warn" role="status">
          ⚠ Source issue: {failing.map((s) => s.source).join(", ")} – showing last good data
        </span>
      )}
    </div>
  );
}
