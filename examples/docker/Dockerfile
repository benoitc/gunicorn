FROM python:3.8.4-slim
ENV PYTHONIOENCODING UTF-8
ENV CONFIG_FILE_PATH=/config/config.py
ENV WORK_DIR=/work
WORKDIR /work

COPY config /config
RUN chmod 777 /config/install.sh /config/start.sh /config/config.sh &&\
    pip3 install -r /config/requirements.txt &&\
    /config/install.sh

ENTRYPOINT /config/start.sh