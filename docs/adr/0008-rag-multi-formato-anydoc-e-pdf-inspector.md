# ADR 0008: RAG Multi-Formato Universal com AnyDoc, Motor Calamine e PDF Inspector

## Contexto

Originalmente, o módulo RAG do Eltanix Coder IDE suportava apenas arquivos PDF através do parser básico em Python (`pypdf`). No entanto:
1. Ambientes corporativos dependem massivamente de documentos de escritório: planilhas Excel (`.xlsx`, `.xls`, `.xlsb`, `.ods`), relatórios Word (`.docx`, `.odt`), apresentações PowerPoint (`.pptx`, `.odp`), arquivos CSV, EPUB e RTF.
2. Parsers tradicionais em Python (`openpyxl`, `python-docx`, `pypdf`) são lentos para arquivos grandes e não preservam tabelas Markdown estruturadas para RAG e LLMs.
3. PDFs digitalizados/escaneados sem camada vetorial de texto consumiam processamento de embedding sem produzir conteúdo textual útil.

## Decisão

Adotar uma arquitetura de extração multi-formato em **Rust nativo** de alta velocidade através das bibliotecas:

1. **`firecrawl-anydoc` com Motor `calamine`**:
   - Conversão universal de arquivos de escritório em GitHub-Flavored Markdown (tabelas, listas, cabeçalhos) em sub-5ms.
   - Utilização do motor em Rust puro **Calamine** (`firecrawl/calamine`) para decodificação *lazy* de planilhas Excel e OpenDocument sem sobrecarga de memória RAM.
   - Formatos suportados: `.docx`, `.doc`, `.docm`, `.xlsx`, `.xls`, `.xlsb`, `.xlsm`, `.pptx`, `.ppt`, `.ppsx`, `.odt`, `.ods`, `.odp`, `.rtf`, `.epub`, `.csv`, `.tsv`, `.md`, `.txt`.

2. **`pdf-inspector` para PDFs**:
   - Classificação rápida em Rust do tipo de PDF (`text_based`, `scanned`, `image_based`, `mixed`).
   - Detecção antecipada de documentos escaneados que necessitam de OCR, evitando ingestão de chunks vazios.
   - Fallback transparente e resiliente para `pypdf` em caso de formato PDF fora de especificação.

3. **Geração de Embeddings Unificada**:
   - Mantém a regra do ADR 0001: todos os chunks gerados pelos parsers fluem pelo `RouterEngine.embed()`, garantindo governança, contabilidade de custos e consistência de vetores no PostgreSQL/pgvector.

## Consequências

- **Positivas**:
  - Ingestão instantânea de múltiplos formatos corporativos sem dependências pesadas de Java/LibreOffice.
  - Tabelas de planilhas e relatórios são indexadas com semântica Markdown perfeita para busca vetorial e GraphRAG.
  - Tratamento inteligente de PDFs com indicação explícita quando houver necessidade de OCR.
- **Negativas / Limitações**:
  - Requer que o ambiente de execução disponha das extensões compiladas de Rust (`anydoc` e `pdf-inspector`), o que é garantido pelo Dockerfile multi-stage com `uv`.
