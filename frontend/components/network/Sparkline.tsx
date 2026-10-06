"use client";

import { useMemo } from "react";
import clsx from "clsx";

export interface SparklineProps {
  data: number[];
  /** Line + fill color (hex). */
  color: string;
  /** Unique suffix for the gradient def - panels can render several. */
  id: string;
  viewWidth?: number;
  viewHeight?: number;
  className?: string;
}

/**
 * Minimal dependency-free sparkline: normalized polyline with a soft gradient
 * area fill and an end-point marker. Rendered with `preserveAspectRatio=none`
 * so it stretches to whatever box the panel gives it.
 */
export default function Sparkline({
  data,
  color,
  id,
  viewWidth = 260,
  viewHeight = 56,
  className,
}: SparklineProps) {
  const { linePath, areaPath, lastPoint, gradientId } = useMemo(() => {
    const min = Math.min(...data);
    const max = Math.max(...data);
    const span = max - min || 1;
    const stepX = viewWidth / Math.max(1, data.length - 1);

    const points = data.map((value, index) => {
      const x = index * stepX;
      const y = viewHeight - 5 - ((value - min) / span) * (viewHeight - 12);
      return [x, y] as const;
    });

    const line = points
      .map(
        ([x, y], index) =>
          `${index === 0 ? "M" : "L"}${x.toFixed(2)},${y.toFixed(2)}`,
      )
      .join(" ");

    return {
      linePath: line,
      areaPath: `${line} L${viewWidth},${viewHeight} L0,${viewHeight} Z`,
      lastPoint: points[points.length - 1],
      gradientId: `spark-gradient-${id}`,
    };
  }, [data, viewWidth, viewHeight, id]);

  return (
    <svg
      viewBox={`0 0 ${viewWidth} ${viewHeight}`}
      preserveAspectRatio="none"
      className={clsx("w-full", className)}
      aria-hidden="true"
    >
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.32" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={areaPath} fill={`url(#${gradientId})`} />
      <path
        d={linePath}
        fill="none"
        stroke={color}
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {lastPoint && (
        <circle cx={lastPoint[0]} cy={lastPoint[1]} r="2.4" fill={color} />
      )}
    </svg>
  );
}
