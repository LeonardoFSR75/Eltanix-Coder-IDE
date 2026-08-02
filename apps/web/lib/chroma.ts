"use client";

export interface ChromaVectorChunk {
  id: string;
  documentId: string;
  filename: string;
  text: string;
  metadata: {
    pageNumber: number;
    chunkIndex: number;
    embeddingModel: string;
  };
  embedding: number[]; // Projeção 2D de coordenadas x, y para visualização
  similarityScore?: number;
}

export interface ChromaCollection {
  name: string;
  vectorCount: number;
  dimension: number;
  createdAt: string;
}

// Simulador & Utilitário para o Banco de Vetores ChromaDB
export class ChromaClient {
  private static STORAGE_KEY = "sicoobito_chroma_vectors";

  // Retorna coleções ativas
  static getCollections(): ChromaCollection[] {
    return [
      {
        name: "relatorios_tecnicos",
        vectorCount: 142,
        dimension: 1536,
        createdAt: "2026-07-28T14:20:00Z",
      },
      {
        name: "mcp_docs",
        vectorCount: 68,
        dimension: 1536,
        createdAt: "2026-07-30T09:15:00Z",
      },
      {
        name: "second_brain_embeddings",
        vectorCount: 35,
        dimension: 1536,
        createdAt: "2026-08-01T11:00:00Z",
      },
    ];
  }

  // Gera vetores com pontos x, y para visualização no gráfico 2D
  static getVectors(): ChromaVectorChunk[] {
    if (typeof window === "undefined") return [];
    const item = localStorage.getItem(this.STORAGE_KEY);
    if (item) {
      return JSON.parse(item);
    }

    const defaultVectors: ChromaVectorChunk[] = [
      {
        id: "chunk-1",
        documentId: "pdf-1",
        filename: "Relatorio_Tecnico_IA_2026.pdf",
        text: "O SicoobitoCode utiliza ChromaDB para armazenamento e indexação semântica de alta performance.",
        metadata: { pageNumber: 1, chunkIndex: 0, embeddingModel: "text-embedding-3-small" },
        embedding: [0.25, 0.45],
      },
      {
        id: "chunk-2",
        documentId: "pdf-1",
        filename: "Relatorio_Tecnico_IA_2026.pdf",
        text: "Os documentos PDF são fatiados em janelas de 512 tokens mantendo contextos entre parágrafos.",
        metadata: { pageNumber: 3, chunkIndex: 1, embeddingModel: "text-embedding-3-small" },
        embedding: [0.32, 0.51],
      },
      {
        id: "chunk-3",
        documentId: "pdf-2",
        filename: "Manual_Protocolo_MCP_v2.pdf",
        text: "O transporte STDIO do MCP garante baixa latência entre o processo pai e sub-processos do agente.",
        metadata: { pageNumber: 2, chunkIndex: 0, embeddingModel: "text-embedding-3-small" },
        embedding: [-0.4, 0.15],
      },
      {
        id: "chunk-4",
        documentId: "pdf-2",
        filename: "Manual_Protocolo_MCP_v2.pdf",
        text: "Servidores SSE permitem conexão remota com autenticação tokenizada e transmissão de eventos.",
        metadata: { pageNumber: 5, chunkIndex: 2, embeddingModel: "text-embedding-3-small" },
        embedding: [-0.48, 0.22],
      },
      {
        id: "chunk-5",
        documentId: "pdf-1",
        filename: "Relatorio_Tecnico_IA_2026.pdf",
        text: "Métricas de auditoria monitoram todas as chamadas de API e previnem injeções de prompt maliciosas.",
        metadata: { pageNumber: 12, chunkIndex: 4, embeddingModel: "text-embedding-3-small" },
        embedding: [0.1, -0.6],
      },
      {
        id: "chunk-6",
        documentId: "pdf-1",
        filename: "Relatorio_Tecnico_IA_2026.pdf",
        text: "Redes neurais locais podem ser treinadas para reranking de resultados recuperados do ChromaDB.",
        metadata: { pageNumber: 15, chunkIndex: 6, embeddingModel: "text-embedding-3-small" },
        embedding: [0.65, -0.2],
      },
    ];

    localStorage.setItem(this.STORAGE_KEY, JSON.stringify(defaultVectors));
    return defaultVectors;
  }

  // Adiciona novos vetores fatiados de um PDF
  static addPDFToChroma(pdfId: string, filename: string, rawText: string, chunkSize = 512): ChromaVectorChunk[] {
    const existing = this.getVectors();
    const sentences = rawText.split(/(?<=[.?!])\s+/).filter((s) => s.length > 10);
    const newChunks: ChromaVectorChunk[] = [];

    sentences.forEach((sentence, idx) => {
      // Coordenadas simuladas de embedding em 2D (-1 a 1)
      const x = Math.sin(idx * 1.5 + pdfId.length) * 0.8;
      const y = Math.cos(idx * 1.5 + pdfId.length) * 0.8;

      newChunks.push({
        id: `chunk-${pdfId}-${idx}-${Date.now()}`,
        documentId: pdfId,
        filename: filename,
        text: sentence,
        metadata: {
          pageNumber: Math.floor(idx / 3) + 1,
          chunkIndex: idx,
          embeddingModel: "text-embedding-3-small",
        },
        embedding: [Number(x.toFixed(2)), Number(y.toFixed(2))],
      });
    });

    const updated = [...existing, ...newChunks];
    if (typeof window !== "undefined") {
      localStorage.setItem(this.STORAGE_KEY, JSON.stringify(updated));
    }
    return updated;
  }

  // ✅ INTEGRAÇÃO SEGUNDO CÉREBRO <-> CHROMADB: Vetorização de notas de conhecimento
  static addNoteToChroma(noteId: string, title: string, content: string): ChromaVectorChunk[] {
    const existing = this.getVectors();
    // Remove vetores antigos dessa nota se existirem
    const filtered = existing.filter((v) => v.documentId !== noteId);

    const sentences = content.split(/(?<=[.?!])\s+/).filter((s) => s.length > 8);
    const newChunks: ChromaVectorChunk[] = [];

    sentences.forEach((sentence, idx) => {
      const x = Math.cos(idx * 1.8 + noteId.length) * 0.75;
      const y = Math.sin(idx * 1.8 + noteId.length) * 0.75;

      newChunks.push({
        id: `chunk-note-${noteId}-${idx}`,
        documentId: noteId,
        filename: `[Nota] ${title}`,
        text: sentence,
        metadata: {
          pageNumber: 1,
          chunkIndex: idx,
          embeddingModel: "text-embedding-3-small",
        },
        embedding: [Number(x.toFixed(2)), Number(y.toFixed(2))],
      });
    });

    const updated = [...filtered, ...newChunks];
    if (typeof window !== "undefined") {
      localStorage.setItem(this.STORAGE_KEY, JSON.stringify(updated));
    }
    return updated;
  }

  // Executa busca por similaridade de cosseno simulada
  static querySimilarity(query: string, topK = 4): ChromaVectorChunk[] {
    const vectors = this.getVectors();
    const queryLower = query.toLowerCase();

    const scored = vectors.map((v) => {
      let matchCount = 0;
      const words = queryLower.split(" ").filter((w) => w.length > 2);
      words.forEach((word) => {
        if (v.text.toLowerCase().includes(word)) matchCount++;
      });

      // Similaridade simulada de 0.60 a 0.99 baseada em palavras-chave
      const baseScore = 0.62 + (matchCount / (words.length || 1)) * 0.35;
      const score = Math.min(0.99, Number((baseScore + Math.random() * 0.05).toFixed(3)));

      return {
        ...v,
        similarityScore: score,
      };
    });

    return scored.sort((a, b) => (b.similarityScore || 0) - (a.similarityScore || 0)).slice(0, topK);
  }
}
