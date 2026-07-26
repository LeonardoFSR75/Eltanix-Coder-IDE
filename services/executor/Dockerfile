FROM python:3.12-slim

WORKDIR /srv

# Superfície mínima: este container tem acesso ao daemon do Docker, então cada
# pacote instalado aqui é um pacote com esse poder ao alcance.
RUN pip install --no-cache-dir \
    "fastapi==0.118.0" \
    "uvicorn==0.34.0" \
    "docker==7.1.0" \
    "pydantic==2.11.0"

COPY app.py ./

ENV PYTHONUNBUFFERED=1

EXPOSE 5402

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "5402"]
