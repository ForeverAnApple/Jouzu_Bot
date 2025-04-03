FROM python:3.13

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends fonts-noto-cjk ffmpeg

COPY fonts/NotoEmoji-VariableFont_wght.ttf /usr/share/fonts/NotoEmoji-VariableFont_wght.ttf

COPY requirements.txt ./

RUN pip install --no-cache-dir -r requirements.txt

RUN mkdir -p /app/data

COPY . .

CMD ["python", "main.py"]
