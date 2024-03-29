FROM python:3.12-slim

WORKDIR /usr/src/app

ENV PYTHONUNBUFFERED=1

ARG APP_VERSION
ENV APP_VERSION=$APP_VERSION

ADD requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

ADD telegram_bot telegram_bot
ADD main.py .
ADD reminder.py .
ADD setup.py .

CMD python -B -O main.py
