FROM python:3.12-slim

WORKDIR /srv

# Superfície mínima, no mesmo espírito do executor: este container roda um
# navegador de verdade com rede real (ver docker-compose.yml, `browser_net`),
# então cada pacote aqui é superfície a mais numa fronteira que já é a mais
# permissiva de rede do sistema.
RUN pip install --no-cache-dir \
    "fastapi==0.118.0" \
    "uvicorn==0.34.0" \
    "playwright==1.48.0" \
    "pydantic==2.11.0"

# Chromium + as bibliotecas de sistema que ele precisa (--with-deps) — sem
# isto o navegador falha ao abrir por falta de libs gráficas do slim.
RUN playwright install --with-deps chromium

COPY app.py ./

ENV PYTHONUNBUFFERED=1

EXPOSE 5406

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "5406"]
