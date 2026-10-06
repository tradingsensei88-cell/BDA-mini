"use client";

import { useCallback, useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { AnimatePresence, motion } from "framer-motion";
import clsx from "clsx";
import Header from "@/components/layout/Header";
import Sidebar, { SIDEBAR_WIDTH } from "@/components/layout/Sidebar";

export interface MainLayoutProps {
  children: React.ReactNode;
}

/**
 * Application shell: collapsible sidebar (desktop) / slide-in drawer (mobile),
 * sticky command header, and an animated main content region.
 */
export default function MainLayout({ children }: MainLayoutProps) {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  const closeMobileNav = useCallback(() => setMobileNavOpen(false), []);

  /* Close the mobile drawer whenever the route changes. */
  useEffect(() => {
    setMobileNavOpen(false);
  }, [pathname]);

  /* Escape closes the mobile drawer. */
  useEffect(() => {
    if (!mobileNavOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMobileNavOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [mobileNavOpen]);

  /* Prevent body scroll while the drawer is open. */
  useEffect(() => {
    document.body.style.overflow = mobileNavOpen ? "hidden" : "";
    return () => {
      document.body.style.overflow = "";
    };
  }, [mobileNavOpen]);

  return (
    <div className="flex h-dvh overflow-hidden bg-cyber-bg">
      {/* Desktop sidebar */}
      <Sidebar
        collapsed={collapsed}
        onToggle={() => setCollapsed((value) => !value)}
        className="hidden md:flex"
      />

      {/* Mobile drawer */}
      <AnimatePresence>
        {mobileNavOpen && (
          <>
            <motion.div
              key="nav-backdrop"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.2 }}
              onClick={closeMobileNav}
              className="fixed inset-0 z-40 bg-cyber-bg/70 backdrop-blur-sm md:hidden"
              aria-hidden="true"
            />
            <motion.div
              key="nav-drawer"
              initial={{ x: -SIDEBAR_WIDTH }}
              animate={{ x: 0 }}
              exit={{ x: -SIDEBAR_WIDTH }}
              transition={{ type: "spring", stiffness: 360, damping: 36 }}
              className="fixed inset-y-0 left-0 z-50 w-[280px] md:hidden"
            >
              <Sidebar
                isMobile
                onToggle={closeMobileNav}
                onNavigate={closeMobileNav}
                className="h-full"
              />
            </motion.div>
          </>
        )}
      </AnimatePresence>

      {/* Main column */}
      <div className="relative flex min-w-0 flex-1 flex-col">
        <Header onOpenMobileNav={() => setMobileNavOpen(true)} />

        <main
          id="main-content"
          className={clsx(
            "relative flex-1 overflow-y-auto bg-cyber-grid-fixed",
          )}
        >
          {/* Dot-matrix overlay with a radial fade */}
          <div
            className="cyber-dots cyber-dots-fade pointer-events-none absolute inset-0"
            aria-hidden="true"
          />
          {/* Ambient top glow */}
          <div
            className="pointer-events-none absolute inset-x-0 top-0 h-64 bg-cyber-radial"
            aria-hidden="true"
          />

          <div className="relative mx-auto w-full max-w-[1600px] px-4 py-6 md:px-6 md:py-8 lg:px-8">
            <AnimatePresence mode="wait" initial={false}>
              <motion.div
                key={pathname}
                initial={{ opacity: 0, y: 14 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -8 }}
                transition={{ duration: 0.28, ease: [0.22, 1, 0.36, 1] }}
              >
                {children}
              </motion.div>
            </AnimatePresence>
          </div>
        </main>
      </div>
    </div>
  );
}
