
## **Docker**

If you are using a Docker container, you can deploy Django and Flask using Gunicorn.

The environment variables used are based on the configuration document below.  
[Configuration Document](https://github.com/benoitc/gunicorn/blob/master/examples/example_config.py)
### **Installation**

Dockerfile Build   

```shell script
$ cd docker
$ docker build --tag [IMAGE_NAME]:[VERSION]
```

example
```shell script
$ docker build --tag gunicorn:0.1 .
```

---
### **Usage**

Basic usage:  
**You need to mount the application you use for the /work folder via docker's -v (volume) option.**  
**The `requirements.txt` file, which records the library dependencies of your Python application, specifies the path through the following environment variable: `$REQUIRENMENTS_FILE_PATH`**

```shell script
$ docker run -it -v [WORK_DIR_PATH]:/work/ \  
              -e REQUIRENMENTS_FILE_PATH=/some/path \
              [OPTIONS] \
              [DOCKER_IMAGE] 
```

example
```shell script
 $ docker run -it -v ${PWD}:/work/  \
              -e REQUIRENMENTS_FILE_PATH=/work/requirements.txt \
              -e START_OPTION=main:app \
              -e WORKER_CLASS=gevent \
              -e BIND='0.0.0.0:80' \
              0b46bd4396d8
```

### **requirements.txt**  
You need to record the framework you use in your `requirements.txt` file as a dependency.  

example:  
```shell script

$ cat requirements.txt

flask==1.1.2

```
    
    
---
### **Configuration**

### Environment variables required
* START_OPTION  
    * It means `APP_MODULE`.



All other environment variables are based on the following documentation.  
[Configuration Document](https://github.com/benoitc/gunicorn/blob/master/examples/example_config.py)

* Additional environment variables  
`FRAMEWORK_VERSION`  
`BIND`  
`BACKLOG`  
`WORKERS`  
`WORKER_CLASS`  
`WORKER_CONNECTIONS`  
`TIMEOUT`  
`KEEPALIVE`  
`SPEW`  
`DAEMON`  
`RAW_ENV`  
`PID_FILE`  
`UMASK`  
`USER`  
`GROUP`  
`TMP_PULOAD_DIR`  
`ERROR_LOG`  
`LOG_LEVEL`  
`ACCESS_LOG`  
`ACCESS_LOG_FORMAT`  
`PROC_NAME`  
`THREAD_COUNT`  

