FROM python:3.8.4-slim
ENV PYTHONIOENCODING UTF-8
ARG DEBIAN_FRONTEND=noninteractive

COPY ./config /config

ENV CONFIG_FILE_PATH=/config/config.py
ENV WORK_DIR=/work

RUN chmod 777 /config/install.sh /config/start.sh /config/config.sh &&\
    pip3 install -r /config/async-requirements.txt &&\
    pip3 install -r /config/sync-requirements.txt &&\
    /config/install.sh

WORKDIR /work
ENTRYPOINT /config/start.sh

