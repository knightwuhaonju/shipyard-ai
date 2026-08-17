FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml ./
COPY apps ./apps

RUN pip install --no-cache-dir .

RUN groupadd --system shipyard \
    && useradd --system --gid shipyard --create-home shipyard

EXPOSE 8000

USER shipyard

CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
