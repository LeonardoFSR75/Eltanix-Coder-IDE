"""Integração com o Cisco AI Defense MCP Scanner.

Permite escanear servidores e ferramentas MCP em busca de ameaças de segurança,
vulnerabilidades, prompt injection, vazamento de dados e divergências de comportamento
usando motores YARA, LLM-as-a-judge e Cisco AI Defense API.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, cast

import httpx

from eltanix.config import Settings
from eltanix.logging_setup import get_logger
from eltanix.mcp.config import MCPServerConfig

log = get_logger(__name__)


@dataclass(slots=True)
class MCPScanFinding:
    tool_name: str
    analyzer: str
    severity: Literal["safe", "low", "medium", "high", "critical", "unknown"]
    rule_id: str
    message: str
    description: str = ""
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class MCPScanResult:
    server_name: str
    status: Literal["safe", "warning", "threat", "error", "skipped"]
    tools_scanned: int
    findings_count: int
    findings: list[MCPScanFinding]
    error: str | None = None
    scanned_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "server_name": self.server_name,
            "status": self.status,
            "tools_scanned": self.tools_scanned,
            "findings_count": self.findings_count,
            "findings": [asdict(f) for f in self.findings],
            "error": self.error,
            "scanned_at": self.scanned_at,
        }


class MCPScannerService:
    """Serviço que orquestra escaneamentos de segurança MCP."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.scanner_url = settings.mcp_scanner_url or os.getenv(
            "MCP_SCANNER_URL", "http://mcp-scanner:8000"
        )

    async def check_health(self) -> dict[str, Any]:
        """Verifica se o serviço ou container do scanner está disponível."""
        # 1. Tenta verificar serviço REST API
        if self.scanner_url:
            try:
                async with httpx.AsyncClient(timeout=3.0) as client:
                    resp = await client.get(f"{self.scanner_url}/health")
                    if resp.status_code == 200:
                        return {
                            "available": True,
                            "mode": "api_server",
                            "url": self.scanner_url,
                        }
            except Exception:
                pass

        # 2. Tenta verificar CLI local ou Docker
        if shutil.which("docker") or shutil.which("mcp-scanner"):
            return {
                "available": True,
                "mode": "docker_or_cli",
                "image": "cisco-mcp-scanner:latest",
            }

        return {
            "available": False,
            "mode": "none",
            "message": "Nenhum endpoint ou container do Cisco MCP Scanner disponível.",
        }

    async def scan_server(
        self,
        server: MCPServerConfig,
        analyzers: list[str] | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> MCPScanResult:
        """Escaneia um servidor MCP específico."""
        active_analyzers = analyzers or ["yara"]

        # Se temos as ferramentas já listadas e a API REST do scanner está ativa:
        if tools and self.scanner_url:
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.post(
                        f"{self.scanner_url}/scan-all-tools",
                        json={
                            "tools": tools,
                            "analyzers": [a.upper() for a in active_analyzers],
                        },
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        return self._parse_api_response(server.name, len(tools), data)
            except Exception as exc:
                log.debug("mcp.scanner.api_fallback", error=str(exc))

        # Fallback via Docker / CLI para análise estática e stdio
        return await self._scan_via_docker(server, active_analyzers)

    async def _scan_via_docker(
        self, server: MCPServerConfig, analyzers: list[str]
    ) -> MCPScanResult:
        """Executa scan do servidor através do container docker cisco-mcp-scanner."""
        if not shutil.which("docker"):
            return MCPScanResult(
                server_name=server.name,
                status="error",
                tools_scanned=0,
                findings_count=0,
                findings=[],
                error="Docker não encontrado no host para executar o escaneamento.",
            )

        cmd = [
            "docker",
            "run",
            "--rm",
            "--network",
            "eltanix_default",
        ]

        # Injeta variáveis de ambiente configuradas no servidor
        for k, v in server.env.items():
            cmd.extend(["-e", f"{k}={v}"])

        if self.settings.openai_api_key:
            cmd.extend(["-e", f"OPENAI_API_KEY={self.settings.openai_api_key}"])

        cmd.extend(
            [
                "cisco-mcp-scanner",
                "--format",
                "raw",
                "--analyzers",
                ",".join(analyzers),
            ]
        )

        if server.transport == "stdio":
            if not server.command:
                return MCPScanResult(
                    server_name=server.name,
                    status="error",
                    tools_scanned=0,
                    findings_count=0,
                    findings=[],
                    error="Servidor stdio sem comando especificado.",
                )
            cmd.extend(["stdio", "--stdio-command", server.command])
            if server.args:
                cmd.extend(["--stdio-args", ",".join(server.args)])
        elif server.transport == "http":
            if not server.url:
                return MCPScanResult(
                    server_name=server.name,
                    status="error",
                    tools_scanned=0,
                    findings_count=0,
                    findings=[],
                    error="Servidor HTTP sem URL especificada.",
                )
            cmd.extend(["remote", "--server-url", server.url])
            if "Authorization" in server.headers:
                token = server.headers["Authorization"].replace("Bearer ", "")
                cmd.extend(["--bearer-token", token])
        else:
            return MCPScanResult(
                server_name=server.name,
                status="skipped",
                tools_scanned=0,
                findings_count=0,
                findings=[],
                error=f"Transporte desconhecido: {server.transport}",
            )

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(process.communicate(), timeout=45.0)
            stdout_str = stdout_bytes.decode(errors="replace").strip()
            stderr_str = stderr_bytes.decode(errors="replace").strip()

            if process.returncode != 0 and not stdout_str:
                log.warning("mcp.scanner.cli_error", code=process.returncode, stderr=stderr_str)
                return MCPScanResult(
                    server_name=server.name,
                    status="error",
                    tools_scanned=0,
                    findings_count=0,
                    findings=[],
                    error=stderr_str or f"Processo encerrou com código {process.returncode}",
                )

            return self._parse_cli_raw_output(server.name, stdout_str)
        except TimeoutError:
            return MCPScanResult(
                server_name=server.name,
                status="error",
                tools_scanned=0,
                findings_count=0,
                findings=[],
                error="Tempo limite de escaneamento esgotado (45s).",
            )
        except Exception as exc:
            log.error("mcp.scanner.exception", error=str(exc))
            return MCPScanResult(
                server_name=server.name,
                status="error",
                tools_scanned=0,
                findings_count=0,
                findings=[],
                error=str(exc),
            )

    def _parse_api_response(self, server_name: str, tools_count: int, data: Any) -> MCPScanResult:
        findings: list[MCPScanFinding] = []
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            items = data.get("findings", []) or data.get("results", [])
        else:
            items = []

        status: Literal["safe", "warning", "threat", "error"] = "safe"
        for item in items:
            sev = str(item.get("severity", "unknown")).lower()
            if sev in ("high", "critical"):
                status = "threat"
            elif sev in ("medium", "low") and status != "threat":
                status = "warning"

            parsed_sev = cast(
                Literal["safe", "low", "medium", "high", "critical", "unknown"],
                sev if sev in ("safe", "low", "medium", "high", "critical") else "unknown",
            )
            findings.append(
                MCPScanFinding(
                    tool_name=item.get("tool_name", "general"),
                    analyzer=item.get("analyzer", "unknown"),
                    severity=parsed_sev,
                    rule_id=item.get("rule_id", item.get("id", "finding")),
                    message=item.get("message", item.get("title", "")),
                    description=item.get("description", ""),
                    details=item,
                )
            )

        return MCPScanResult(
            server_name=server_name,
            status=status if findings else "safe",
            tools_scanned=tools_count,
            findings_count=len(findings),
            findings=findings,
        )

    def _parse_cli_raw_output(self, server_name: str, raw_output: str) -> MCPScanResult:
        findings: list[MCPScanFinding] = []
        try:
            # Encontra blocos JSON na saída se houver logs misturados
            json_start = raw_output.find("{")
            json_arr_start = raw_output.find("[")
            if json_arr_start != -1 and (json_start == -1 or json_arr_start < json_start):
                json_start = json_arr_start

            if json_start != -1:
                parsed = json.loads(raw_output[json_start:])
                return self._parse_api_response(server_name, 1, parsed)
        except Exception:
            pass

        # Análise heurística caso a saída seja texto simples
        status: Literal["safe", "warning", "threat"] = "safe"
        if "THREAT" in raw_output or "HIGH" in raw_output or "CRITICAL" in raw_output:
            status = "threat"
        elif "WARNING" in raw_output or "MEDIUM" in raw_output:
            status = "warning"

        return MCPScanResult(
            server_name=server_name,
            status=status,
            tools_scanned=1,
            findings_count=len(findings),
            findings=findings,
        )
