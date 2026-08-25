# ADR 0010 — Segurança de Servidores MCP e Cisco AI Defense Scanner

**Status:** aceito · **Data:** 2026-08-19

## Contexto

A plataforma Eltanix Coder IDE suporta o protocolo aberto Model Context Protocol (MCP) para conectar servidores de ferramentas externos (via processos `stdio` ou requisições HTTP). Como servidores MCP externos podem ser mantidos por terceiros ou expor ações com potencial de alteração do workspace, é indispensável estabelecer um modelo estrito de segurança, auditoria e classificação de risco para evitar injeções de prompt indiretas (*Prompt Injection*), exfiltração de dados ou chamadas maliciosas.

## Decisão

1. **Varredura Preventiva com Cisco AI Defense Scanner**:
   - Todo servidor MCP cadastrado é submetido à varredura estática e dinâmica pelo módulo `eltanix.mcp.scanner` (utilizando analisadores YARA, regras estáticas e motores *LLM-as-a-Judge*).
   - Servidores ou ferramentas marcados com severidade `high` ou `critical` são automaticamente desativados e bloqueados de execução.

2. **Atribuição Padrão de RiskClass**:
   - Por padrão, toda ferramenta exposta por um servidor MCP nasce com `RiskClass.WRITE`, exigindo obrigatoriamente a aprovação humana via `interrupt()` do LangGraph antes de ser executada.
   - Uma ferramenta MCP só pode ser convertida para `RiskClass.READ` (execução automática sem pausa) se o servidor for explicitamente configurado com `trust_annotations: true` e a ferramenta contiver o metadado oficial `read_only_hint: true`.

3. **Isolamento de Processos**:
   - Conexões `stdio` para servidores MCP no ambiente Windows/Linux são isoladas e monitoradas para prevenir travamentos de I/O em pipes ou tentativas de acesso não autorizado ao sistema operacional.

## Alternativas consideradas

- **Confiar cegamente nas ferramentas MCP externas** — Risco inaceitável de *Prompt Injection* e exfiltração de arquivos do repositório. Rejeitado.
- **Exigir aprovação humana para 100% das ferramentas MCP sem exceção** — Torna o uso de ferramentas de leitura (ex: consultar um banco de dados de documentação via MCP) extremamente lento e burocrático para o desenvolvedor. Rejeitado em favor do modelo `trust_annotations` + `read_only_hint`.

## Consequências

- Segurança de nível enterprise para integração de ferramentas de terceiros via MCP.
- Transparência total e rastreabilidade na trilha de auditoria para ações executadas via MCP.
