# Build from repository root: docker build -f src/demo/Dockerfile .
FROM python:3.12-slim
WORKDIR /app
COPY requirements.lock ./
RUN pip install --no-cache-dir --require-hashes -r requirements.lock
COPY src ./src
RUN useradd --create-home chatbot && mkdir instance && chown chatbot:chatbot instance
USER chatbot
ENV HOST=0.0.0.0 PORT=8080 CHAT_PROVIDER=local COOKIE_SECURE=true
EXPOSE 8080
CMD ["python", "-m", "src.demo.app"]
