import Link from "next/link";

export function Footer() {
  return (
    <footer className="border-t border-zinc-800 bg-zinc-950">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-12">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-8">
          <div className="col-span-2 md:col-span-1">
            <span className="text-lg font-bold">
              <span className="text-teal-500">Silo</span>
              <span className="text-white">Crawl</span>
            </span>
            <p className="mt-2 text-sm text-zinc-400 max-w-xs">
              Open-source, LLM-powered web scraping toolkit.
            </p>
          </div>

          <div>
            <h4 className="text-sm font-medium text-white mb-3">Product</h4>
            <ul className="space-y-2 text-sm text-zinc-400">
              <li><Link href="/playground" className="hover:text-white transition-colors">Playground</Link></li>
              <li><Link href="/docs" className="hover:text-white transition-colors">Docs</Link></li>
            </ul>
          </div>

          <div>
            <h4 className="text-sm font-medium text-white mb-3">API</h4>
            <ul className="space-y-2 text-sm text-zinc-400">
              <li><Link href="/docs#scrape" className="hover:text-white transition-colors">Scrape</Link></li>
              <li><Link href="/docs#crawl" className="hover:text-white transition-colors">Crawl</Link></li>
              <li><Link href="/docs#map" className="hover:text-white transition-colors">Map</Link></li>
              <li><Link href="/docs#extract" className="hover:text-white transition-colors">Extract</Link></li>
            </ul>
          </div>

          <div>
            <h4 className="text-sm font-medium text-white mb-3">Community</h4>
            <ul className="space-y-2 text-sm text-zinc-400">
              <li>
                <a href="https://github.com/you/silocrawl" target="_blank" rel="noopener noreferrer"
                  className="hover:text-white transition-colors">GitHub</a>
              </li>
            </ul>
          </div>
        </div>

        <div className="mt-10 border-t border-zinc-800 pt-6 flex items-center justify-between">
          <p className="text-xs text-zinc-500">© 2026 SiloCrawl.</p>
        </div>
      </div>
    </footer>
  );
}
