FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOST=0.0.0.0 PORT=8000
WORKDIR /app
COPY server.py /app/server.py
RUN mkdir -p /data && useradd --system --uid 10001 onair && chown -R onair:onair /app /data
USER onair
EXPOSE 8000
CMD ["python", "/app/server.py"]
