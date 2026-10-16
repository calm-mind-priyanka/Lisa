FROM python:3.10-slim

WORKDIR /app

COPY . .

RUN pip install --no-cache-dir -r requirements.txt

# Lets Koyeb know we are exposing this port for FastAPI health check
EXPOSE 8080

CMD ["python3", "bot.py"]
