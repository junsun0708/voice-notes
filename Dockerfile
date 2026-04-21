# 참고용 Dockerfile — 실제 배포는 구독 인증(claude login) 때문에 호스트 실행을 권장합니다.
# Docker 로 돌리려면 컨테이너 안에서 별도로 `claude login` 이 되어 있어야 합니다.
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    tzdata \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN useradd --create-home appuser \
    && mkdir -p /app/inbox /app/outputs /app/processing /app/processed /app/failed \
    && chown -R appuser:appuser /app
USER appuser

CMD ["python", "-m", "src.main"]
