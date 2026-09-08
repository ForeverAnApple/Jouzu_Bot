FROM python:3.14

WORKDIR /app

# Without a tty stdout is block-buffered, so anything printed is invisible in docker logs.
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg

COPY requirements.txt ./

RUN pip install --no-cache-dir -r requirements.txt

RUN mkdir -p /app/data

COPY . .

CMD ["python", "main.py"]
