import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import { HeaderNav } from "@/components/HeaderNav";
import { ThemeProvider } from "@/lib/theme";
import { ToastProvider } from "@/components/Toast";
import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-jetbrains",
  display: "swap",
});

export const metadata: Metadata = {
  title: "SicoobitoCode — Agente & Gateway Multi-Modelo",
  description: "Gateway multi-modelo local-first com contabilidade de custo, agentic IDE e suporte a Pyright LSP",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="pt-BR" className={`${inter.variable} ${jetbrainsMono.variable}`} data-theme="dark">
      <body>
        <ThemeProvider>
          <ToastProvider>
            <div className="app-root">
              <HeaderNav />
              {children}
            </div>
          </ToastProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
