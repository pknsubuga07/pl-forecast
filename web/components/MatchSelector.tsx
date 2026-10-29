"use client";

import { useRouter } from "next/navigation";

export function MatchSelector({ current, options, basePath = "/match" }: { current: string; options: { id: string; label: string }[]; basePath?: string }) {
  const router = useRouter();
  return (
    <>
      <label htmlFor="match-select" className="sr-only">Choose a fixture</label>
      <select
        id="match-select"
        value={current}
        onChange={(e) => router.push(`${basePath}/${e.target.value}`)}
        className="w-full max-w-sm rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink sm:w-auto"
      >
        {options.map((o) => (
          <option key={o.id} value={o.id}>{o.label}</option>
        ))}
      </select>
    </>
  );
}
