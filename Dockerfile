FROM python:3.11-slim

WORKDIR /usr/src/app

ENV PYTHONUNBUFFERED=1

ADD requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

ADD telegram_bot telegram_bot
ADD main.py .
ADD setup.py .

CMD python -B -O main.py
