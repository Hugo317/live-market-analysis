FROM python:3.13-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY data/snapshot.db ./data/snapshot.db
RUN pip install --no-cache-dir . gunicorn
ENV PORT=7860
EXPOSE 7860
CMD ["sh", "-c", "gunicorn live_market_analysis.dashboard.app:server -b 0.0.0.0:${PORT} --workers 1 --timeout 120"]
