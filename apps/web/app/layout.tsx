import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import { HeaderNav } from "@/components/HeaderNav";
import { ThemeProvider } from "@/lib/theme";
import { ToastProvider } from "@/components/Toast";
import { AuthProvider } from "@/components/providers/AuthContext";
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
  title: "SicoobitoCode — Agente, RAG & Segundo Cérebro",
  description: "Plataforma IA local-first com Segundo Cérebro Obsidian, RAG, Skills, MCP e Auditoria",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="pt-BR" className={`${inter.variable} ${jetbrainsMono.variable}`} data-theme="dark">
      <body>
        <ThemeProvider>
          <ToastProvider>
            <AuthProvider>
              <div className="app-root">
                <HeaderNav />
                {children}
              </div>
            </AuthProvider>
          </ToastProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
