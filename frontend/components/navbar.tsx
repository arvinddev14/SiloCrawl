"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";

const links = [
  { href: "/playground", label: "Playground" },
  { href: "/docs", label: "Docs" },
];

export function Navbar() {
  const path = usePathname();

  return (
    <header className="sticky top-0 z-50 border-b border-zinc-800 bg-zinc-950/80 backdrop-blur-sm">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <div className="flex h-14 items-center justify-between">
          <div className="flex items-center gap-8">
            <Link href="/" className="flex items-center gap-2">
              <span className="text-xl font-bold tracking-tight">
                <span className="text-teal-500">Silo</span>
                <span className="text-white">Crawl</span>
              </span>
            </Link>
            <nav className="hidden md:flex items-center gap-6">
              {links.map((l) => (
                <Link
                  key={l.href}
                  href={l.href}
                  className={cn(
                    "text-sm transition-colors",
                    path === l.href
                      ? "text-white font-medium"
                      : "text-zinc-400 hover:text-white"
                  )}
                >
                  {l.label}
                </Link>
              ))}
            </nav>
          </div>
          <div className="flex items-center gap-3">
            <a
              href="https://github.com/you/silocrawl"
              target="_blank"
              rel="noopener noreferrer"
              className="text-zinc-400 hover:text-white transition-colors text-sm"
            >
              GitHub
            </a>
            <Link
              href="/playground"
              className="rounded-md bg-teal-500 px-3.5 py-1.5 text-sm font-medium text-white hover:bg-teal-600 transition-colors"
            >
              Try it free
            </Link>
          </div>
        </div>
      </div>
    </header>
  );
}
