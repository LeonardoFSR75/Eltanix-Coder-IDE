import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "SicoobitoCode",
  description: "Gateway multi-modelo local-first com contabilidade de custo",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="pt-BR">
      <body>
        <div className="shell">
          <header className="topbar">
            <span className="brand">SicoobitoCode</span>
            <nav className="nav">
              <Link href="/">Custo</Link>
              <Link href="/providers">Provedores</Link>
              <Link href="/requests">Requests</Link>
            </nav>
          </header>
          {children}
        </div>
      </body>
    </html>
  );
}
