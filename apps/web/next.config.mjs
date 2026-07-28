/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  experimental: {
    // Evita empacotar o pacote inteiro do editor de ícones/monaco-react no
    // primeiro bundle — só entra o que cada rota realmente importa.
    optimizePackageImports: ["@monaco-editor/react"],
  },
  async headers() {
    return [
      {
        // Os arquivos do Monaco em public/vs têm hash no nome (imutáveis por
        // build); sem isso o navegador revalida/baixa de novo o core de
        // alguns MB a cada visita.
        source: "/vs/:path*",
        headers: [
          { key: "Cache-Control", value: "public, max-age=31536000, immutable" },
        ],
      },
    ];
  },
};

export default nextConfig;
