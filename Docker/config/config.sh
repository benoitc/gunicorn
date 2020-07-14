#!/bin/bash
echo "" > `echo -e $CONFIG_FILE_PATH` &&\
if [ -n "$BIND" ] && [ ! -z "$BIND" ]; then
  echo "bind='$BIND'" >> `echo -e $CONFIG_FILE_PATH`
fi &&\
if [ -n "$BACKLOG" ] && [ ! -z "$BACKLOG" ];then
  echo "backlog=$BACKLOG" >> `echo -e $CONFIG_FILE_PATH`
fi &&\
if [ -n "$WORKERS" ] && [ ! -z "$WORKERS" ];then
  echo "workers=$WORKERS" >> `echo -e $CONFIG_FILE_PATH`
fi &&\
if [ -n "$WORKER_CLASS" ] && [ ! -z "$WORKER_CLASS" ];then
  echo "worker_class='$WORKER_CLASS'" >> `echo -e $CONFIG_FILE_PATH`
fi &&\
if [ -n "$WORKER_CONNECTIONS" ] && [ ! -z "$WORKER_CONNECTIONS" ];then
  echo "worker_connections=$WORKER_CONNECTIONS" >> `echo -e $CONFIG_FILE_PATH`
fi &&\
if [ -n "$TIMEOUT" ] && [ ! -z "$TIMEOUT" ];then
  echo "timeout=$TIMEOUT" >> `echo -e $CONFIG_FILE_PATH`
fi &&\
if [ -n "$KEEPALIVE" ] && [ ! -z "$KEEPALIVE" ];then
  echo "keepalive=$KEEPALIVE" >> `echo -e $CONFIG_FILE_PATH`
fi &&\
if [ -n "$SPEW" ] && [ ! -z "$SPEW" ];then
  echo "spew=$SPEW" >> `echo -e $CONFIG_FILE_PATH`
fi &&\
if [ -n "$DAEMON" ] && [ ! -z "$DAEMON" ];then
  echo "daemon=$DAEMON" >> `echo -e $CONFIG_FILE_PATH`
fi &&\
if [ -n "$RAW_ENV" ] && [ ! -z "$RAW_ENV" ];then
  echo "raw_env=$RAW_ENV" >> `echo -e $CONFIG_FILE_PATH`
fi &&\
if [ -n "$PID_FILE" ] && [ ! -z "$PID_FILE" ];then
  echo "pidfile=$PID_FILE" >> `echo -e $CONFIG_FILE_PATH`
fi &&\
if [ -n "$UMASK" ] && [ ! -z "$UMASK" ];then
  echo "umask=$UMASK" >> `echo -e $CONFIG_FILE_PATH`
fi &&\
if [ -n "$USER" ] && [ ! -z "$USER" ];then
  echo "user=$USER" >> `echo -e $CONFIG_FILE_PATH`
fi &&\
if [ -n "$GROUP" ] && [ ! -z "$GROUP" ];then
  echo "group=$GROUP" >> `echo -e $CONFIG_FILE_PATH`
fi &&\
if [ -n "$TMP_PULOAD_DIR" ] && [ ! -z "$TMP_PULOAD_DIR" ];then
  echo "tmp_upload_dir=$TMP_PULOAD_DIR" >> `echo -e $CONFIG_FILE_PATH`
fi &&\
if [ -n "$ERROR_LOG" ] && [ ! -z "$ERROR_LOG" ];then
  echo "errorlog=$ERROR_LOG" >> `echo -e $CONFIG_FILE_PATH`
fi &&\
if [ -n "$LOG_LEVEL" ] && [ ! -z "$LOG_LEVEL" ];then
  echo "loglevel='$LOG_LEVEL'" >> `echo -e $CONFIG_FILE_PATH`
fi &&\
if [ -n "$ACCESS_LOG" ] && [ ! -z "$ACCESS_LOG" ];then
  echo "accesslog=$ACCESS_LOG" >> `echo -e $CONFIG_FILE_PATH`
fi &&\
if [ -n "$ACCESS_LOG_FORMAT" ] && [ ! -z "$ACCESS_LOG_FORMAT" ];then
  echo "access_log_format='$ACCESS_LOG_FORMAT'" >> `echo -e $CONFIG_FILE_PATH`
fi &&\
if [ -n "$PROC_NAME" ] && [ ! -z "$PROC_NAME" ];then
  echo "proc_name=$PROC_NAME" >> `echo -e $CONFIG_FILE_PATH`
fi

if [ -n "$THREAD_COUNT" ] && [ ! -z "$THREAD_COUNT" ];then
  echo "threads=$THREAD_COUNT" >> `echo -e $CONFIG_FILE_PATH`
fi

