"""Script para empacotar o release de deploy do Eltanix Coder IDE em formato ZIP."""

from __future__ import annotations

import os
import zipfile
from pathlib import Path

# Diretório raiz do projeto
ROOT_DIR = Path(__file__).parent.parent.resolve()
OUTPUT_ZIP = ROOT_DIR / "eltanix_deploy.zip"

EXCLUDE_DIRS = {
    "node_modules",
    ".venv",
    ".git",
    ".next",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "dist",
    "out",
    "build",
    "graphify-out",
}

EXCLUDE_FILES = {
    ".env",
    "eltanix_deploy.zip",
    ".DS_Store",
}

EXCLUDE_EXTENSIONS = {
    ".pyc",
    ".pyo",
    ".log",
}


def should_exclude(rel_path: Path) -> bool:
    """Verifica se o arquivo ou diretório deve ser excluído do pacote."""
    for part in rel_path.parts:
        if part in EXCLUDE_DIRS:
            return True

    filename = rel_path.name
    if filename in EXCLUDE_FILES:
        return True

    if rel_path.suffix in EXCLUDE_EXTENSIONS:
        return True

    return False


def create_deploy_zip() -> None:
    print(f"[+] Criando arquivo de pacote para deploy: {OUTPUT_ZIP.name}")

    count = 0
    total_uncompressed_bytes = 0

    with zipfile.ZipFile(OUTPUT_ZIP, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for root, dirs, files in os.walk(ROOT_DIR):
            # Filtrar diretórios in-place para não percorrer pastas excluídas
            dirs[:] = [d for d in dirs if not should_exclude(Path(root, d).relative_to(ROOT_DIR))]

            for file in files:
                full_path = Path(root, file)
                rel_path = full_path.relative_to(ROOT_DIR)

                if should_exclude(rel_path):
                    continue

                zip_file.write(full_path, arcname=str(rel_path))
                count += 1
                total_uncompressed_bytes += full_path.stat().st_size

    zip_size_mb = OUTPUT_ZIP.stat().st_size / (1024 * 1024)
    uncompressed_mb = total_uncompressed_bytes / (1024 * 1024)

    print("=================================================")
    print("[SUCCESS] Empacotamento concluido com sucesso!")
    print(f"[*] Arquivo gerado: {OUTPUT_ZIP}")
    print(f"[*] Arquivos empacotados: {count}")
    print(f"[*] Tamanho compactado: {zip_size_mb:.2f} MB (original: {uncompressed_mb:.2f} MB)")
    print("=================================================")


if __name__ == "__main__":
    create_deploy_zip()
