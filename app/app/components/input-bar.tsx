"use client";

import { useState, useRef } from "react";

interface InputBarProps {
  onSend: (text: string) => void;
  disabled: boolean;
  listening?: boolean;
  onVoiceToggle?: () => void;
}

export function InputBar({ onSend, disabled, listening, onVoiceToggle }: InputBarProps) {
  const [text, setText] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  function handleSubmit() {
    const trimmed = text.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setText("");
    inputRef.current?.focus();
  }

  return (
    
    <div className="flex gap-2 w-full items-center">
      


      {/* Input field */}
      <input
        ref={inputRef}
        type="text"
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && handleSubmit()}
        placeholder={disabled ? "Processing..." : "Command JARVIS..."}
        disabled={disabled}
        className="
          hud-input flex-1
          bg-[var(--panel-bg)] border border-[var(--panel-border)] rounded-sm
          px-4 py-2.5 text-xs text-[var(--foreground)]
          placeholder:text-white/20
          focus:outline-none focus:border-[var(--accent)]/40
          disabled:opacity-30
          font-[family-name:var(--font-mono)]
          transition-all duration-300
        "
        autoComplete="off"
      />

      {/* Send button */}
      <button
        onClick={handleSubmit}
        disabled={disabled || !text.trim()}
        className="
          flex-shrink-0 px-4 py-2.5 rounded-sm text-[10px] tracking-[2px] uppercase
          bg-[var(--accent)]/10 border border-[var(--accent)]/25
          text-[var(--accent)]
          hover:bg-[var(--accent)]/20 hover:border-[var(--accent)]/40
          disabled:opacity-20 disabled:cursor-not-allowed
          cursor-pointer transition-all duration-200
          font-[family-name:var(--font-mono)]
        "
      >
        SEND
      </button>
    </div>
  );
}
