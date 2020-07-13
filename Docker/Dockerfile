FROM ubuntu:focal
ENV PYTHONIOENCODING UTF-8
ARG DEBIAN_FRONTEND=noninteractive

# Pypy is installed from a package manager because it takes so long to build.
RUN apt-get update && apt-get install -y build-essential \
    libcurl4-openssl-dev \
    libffi-dev \
    tk-dev \
    xz-utils \
    lsb-release \
    libmemcached-dev \
    make \
    liblzma-dev \
    libreadline-dev \
    libbz2-dev \
    llvm \
    libncurses5-dev \
    libsqlite3-dev \
    wget \
    pypy \
    python-openssl \
    libncursesw5-dev \
    zlib1g-dev \
    pkg-config \
    libssl-dev \
    python3-pip \
    sudo

ENV IS_ASYNC=false

RUN sudo apt-get install -y gunicorn

COPY ./install.sh /install.sh

RUN chmod 777 /install.sh

ENTRYPOINT ["/install.sh"]


