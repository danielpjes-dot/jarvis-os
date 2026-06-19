"use client";

import { ReactNode } from "react";

interface HudPanelProps {
  title?: string;
  children: ReactNode;
  className?: string;
  /** Extra corner decorations */
  corners?: boolean;
  /** Stronger glow variant */
  glow?: boolean;
  onClick?: () => void;
}
export function HudPanel({
  title,
  children,
  className = "",
}: {
  title?: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={`h-full min-h-0 flex flex-col ${className}`}>
      {title && (
        <div className="shrink-0 px-3 py-2 text-[10px] tracking-[3px] uppercase text-[var(--accent)] border-b border-white/10">
          {title}
        </div>
      )}

      {/* 🔥 THIS IS CRITICAL */}
      <div className="flex-1 min-h-0 overflow-hidden">
        {children}
      </div>
    </div>
  );
}