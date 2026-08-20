FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8765
WORKDIR /app
COPY requirements-prod.txt .
RUN pip install --no-cache-dir -r requirements-prod.txt
COPY . .
RUN useradd --create-home --uid 10001 prime && mkdir -p /app/media && chown -R prime:prime /app
RUN chmod +x /app/start_prod.sh
USER prime
EXPOSE 8765
CMD ["/app/start_prod.sh"]
