FROM python:3.10-slim

WORKDIR /usr/src/app

ADD telegram_bot telegram_bot
ADD main.py .
ADD requirements.txt .
ADD setup.py .

RUN pip install --no-cache-dir -r requirements.txt

CMD python -B -O main.py

