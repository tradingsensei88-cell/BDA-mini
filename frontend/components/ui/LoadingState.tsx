"use client";

import clsx from "clsx";

export type LoadingVariant = "card" | "chart" | "table" | "text";

export interface LoadingStateProps {
  variant?: LoadingVariant;
  /** Rows for `table` / lines for `text`. */
  rows?: number;
  className?: string;
  label?: string;
}

/**
 * Skeleton placeholder matching the shape of the content that will replace it.
 * Uses the `.skeleton` shimmer utility defined in globals.css.
 */
export default function LoadingState({
  variant = "card",
  rows = 4,
  className,
  label,
}: LoadingStateProps) {
  return (
    <div
      role="status"
      aria-label={label ?? "Loading content"}
      className={clsx("w-full animate-pulse", className)}
    >
      {variant === "card" && (
        <div className="glass-panel rounded-xl border border-cyber-border/80 p-5">
          <div className="flex items-start justify-between">
            <div className="space-y-3">
              <div className="skeleton h-3 w-28" />
              <div className="skeleton h-7 w-40" />
            </div>
            <div className="skeleton h-10 w-10 rounded-lg" />
          </div>
          <div className="skeleton mt-5 h-2.5 w-24" />
        </div>
      )}

      {variant === "chart" && (
        <div className="glass-panel rounded-xl border border-cyber-border/80 p-5">
          <div className="flex items-center justify-between">
            <div className="skeleton h-3 w-32" />
            <div className="skeleton h-6 w-20 rounded-md" />
          </div>
          <div className="mt-6 flex h-44 items-end gap-2.5">
            {[42, 68, 35, 82, 55, 91, 47, 63, 76, 38, 58, 88].map(
              (height, index) => (
                <div
                  key={index}
                  className="skeleton w-full rounded-t-sm"
                  style={{ height: `${height}%` }}
                />
              ),
            )}
          </div>
        </div>
      )}

      {variant === "table" && (
        <div className="glass-panel overflow-hidden rounded-xl border border-cyber-border/80">
          <div className="border-b border-cyber-border/70 p-4">
            <div className="skeleton h-3 w-36" />
          </div>
          <div className="divide-y divide-cyber-border/50">
            {Array.from({ length: rows }).map((_, index) => (
              <div
                key={index}
                className="grid grid-cols-[1fr_2fr_1fr_0.75fr] items-center gap-4 px-4 py-3.5"
              >
                <div className="skeleton h-2.5 w-full" />
                <div className="skeleton h-2.5 w-4/5" />
                <div className="skeleton h-2.5 w-3/4" />
                <div className="skeleton h-5 w-16 rounded-md" />
              </div>
            ))}
          </div>
        </div>
      )}

      {variant === "text" && (
        <div className="space-y-2.5">
          {Array.from({ length: rows }).map((_, index) => (
            <div
              key={index}
              className="skeleton h-2.5"
              style={{ width: `${[100, 92, 78, 96, 64, 88][index % 6]}%` }}
            />
          ))}
        </div>
      )}

      <span className="sr-only">Loading...</span>
    </div>
  );
}
