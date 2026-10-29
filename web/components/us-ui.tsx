import type { ReactNode } from "react";

export function Logo({ src, alt, size = 28 }: { src: string | null; alt: string; size?: number }) {
  if (!src) {
    return (
      <span aria-hidden style={{ width: size, height: size, fontSize: size * 0.34 }}
        className="grid shrink-0 place-items-center rounded-full bg-surface-2 font-semibold text-ink-2">
        {alt}
      </span>
    );
  }
  // eslint-disable-next-line @next/next/no-img-element
  return <img src={src} alt="" width={size} height={size} loading="lazy" className="shrink-0 object-contain" style={{ width: size, height: size }} />;
}

/** Two-way win probability bar: home (left) vs away (right), always labelled. */
export function WinBar({ pHome, height = 22, labels = true }: { pHome: number; height?: number; labels?: boolean }) {
  const h = Math.round(pHome * 100);
  const a = 100 - h;
  return (
    <div className="flex w-full gap-[2px] overflow-hidden rounded-[5px]" style={{ height }} role="img" aria-label={`Home ${h}%, away ${a}%`}>
      <div className="flex items-center justify-start bg-home pl-2 text-[11px] font-semibold text-white" style={{ width: `${h}%` }} title={`Home ${h}%`}>
        {labels && h >= 12 ? `${h}%` : ""}
      </div>
      <div className="flex items-center justify-end bg-away pr-2 text-[11px] font-semibold text-white" style={{ width: `${a}%` }} title={`Away ${a}%`}>
        {labels && a >= 12 ? `${a}%` : ""}
      </div>
    </div>
  );
}

const RES = { W: "bg-win", L: "bg-loss", T: "bg-draw" };

export function WLPill({ r, title }: { r: "W" | "L" | "T"; title?: string }) {
  return <span title={title} className={`grid h-6 w-6 place-items-center rounded-md text-[11px] font-bold text-white ${RES[r]}`}>{r}</span>;
}

export function Row({ label, home, away }: { label: string; home: ReactNode; away: ReactNode }) {
  return (
    <tr className="border-t border-line">
      <td className="py-1.5 text-ink-2">{label}</td>
      <td className="py-1.5 text-right font-medium">{home}</td>
      <td className="py-1.5 text-right font-medium">{away}</td>
    </tr>
  );
}
