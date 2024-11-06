# You can also use your favorite Python Docker image.
FROM python:3.8.4-slim
ENV WORK_DIR=/work
WORKDIR /work

COPY config /config
RUN chmod 777 /config/start.sh

ENTRYPOINT /config/start.sh