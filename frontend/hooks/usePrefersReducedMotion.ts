"use client";

import { useEffect, useState } from "react";

/**
 * Tracks the `prefers-reduced-motion` user setting. Returns `false` during
 * SSR / first paint and syncs with the media query once mounted.
 */
export default function usePrefersReducedMotion(): boolean {
  const [prefersReducedMotion, setPrefersReducedMotion] = useState(false);

  useEffect(() => {
    const mediaQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setPrefersReducedMotion(mediaQuery.matches);

    update();
    mediaQuery.addEventListener("change", update);
    return () => mediaQuery.removeEventListener("change", update);
  }, []);

  return prefersReducedMotion;
}
