#!/bin/sh
set -e

# Se o primeiro argumento começar com um traço (ex: --help, --scan-known-configs)
# ou for um subcomando conhecido, executa mcp-scanner diretamente.
if [ "$1" = "server" ] || [ "$1" = "api" ]; then
    shift
    exec uvicorn mcpscanner.api.api:app --host 0.0.0.0 --port 8000 "$@"
elif [ "$1" = "sh" ] || [ "$1" = "bash" ] || [ "$1" = "python" ] || [ "$1" = "uvicorn" ]; then
    exec "$@"
else
    exec mcp-scanner "$@"
fi
