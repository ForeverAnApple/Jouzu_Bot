FROM python:3.14

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg

COPY requirements.txt ./

RUN pip install --no-cache-dir -r requirements.txt

RUN mkdir -p /app/data

COPY . .

CMD ["python", "main.py"]
