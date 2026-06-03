"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";

interface CodeBlockProps {
  code: string;
  language?: string;
  className?: string;
}

export function CodeBlock({ code, language = "bash", className }: CodeBlockProps) {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    await navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className={cn("relative rounded-lg border border-zinc-800 bg-zinc-900 overflow-hidden", className)}>
      <div className="flex items-center justify-between px-4 py-2 border-b border-zinc-800">
        <span className="text-xs text-zinc-500 font-mono">{language}</span>
        <button
          onClick={copy}
          className="text-xs text-zinc-400 hover:text-white transition-colors"
        >
          {copied ? "Copied!" : "Copy"}
        </button>
      </div>
      <pre className="overflow-x-auto p-4 text-sm leading-relaxed">
        <code className="font-mono text-zinc-200">{code}</code>
      </pre>
    </div>
  );
}

interface TabCodeBlockProps {
  tabs: { label: string; code: string; language?: string }[];
  className?: string;
}

export function TabCodeBlock({ tabs, className }: TabCodeBlockProps) {
  const [active, setActive] = useState(0);
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    await navigator.clipboard.writeText(tabs[active].code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className={cn("rounded-lg border border-zinc-800 bg-zinc-900 overflow-hidden", className)}>
      <div className="flex items-center justify-between border-b border-zinc-800">
        <div className="flex">
          {tabs.map((t, i) => (
            <button
              key={t.label}
              onClick={() => setActive(i)}
              className={cn(
                "px-4 py-2.5 text-xs font-medium transition-colors border-b-2",
                i === active
                  ? "text-white border-teal-500"
                  : "text-zinc-500 border-transparent hover:text-zinc-300"
              )}
            >
              {t.label}
            </button>
          ))}
        </div>
        <button
          onClick={copy}
          className="px-4 text-xs text-zinc-400 hover:text-white transition-colors"
        >
          {copied ? "Copied!" : "Copy"}
        </button>
      </div>
      <pre className="overflow-x-auto p-4 text-sm leading-relaxed">
        <code className="font-mono text-zinc-200">{tabs[active].code}</code>
      </pre>
    </div>
  );
}
