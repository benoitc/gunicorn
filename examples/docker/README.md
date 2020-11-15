
## **Docker**

If you are using a Docker container, you can deploy Django and Flask using Gunicorn.

The environment variables used are based on the configuration document below.  
[Configuration Document](https://github.com/benoitc/gunicorn/blob/master/examples/example_config.py)
### **Installation**

Dockerfile Build   

```shell script
$ cd ./examples/docker
$ docker build --tag [IMAGE_NAME]:[VERSION] .
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
              -e REQUIRENMENTS_FILE_PATH=/work/sample/requirements.txt \ 
              -e START_OPTION="-b 0.0.0.0:80 sample.main:app" \
              gunicorn:0.1
```
### **requirements.txt**  
You need to record the framework you use in your `requirements.txt` file as a dependency.  

```shell script

# in ./requirements.txt 
...
flask==1.1.2
...

```

### **gunicorn.conf.py**  
If you manage your configuration through the `gunicorn.conf.py` file, you can use the configuration by specifying the location of the `gunicorn.conf.py` file via the `$CONFIG_FILE_PATH` environment variable.
All environment variables other than `$REQUIRENMENTS_FILE_PATH` and `$START_OPTION` are ignored.  

```shell script
 $ docker run -it -v ${PWD}:/work/  \ 
              -e REQUIRENMENTS_FILE_PATH=/work/sample/requirements.txt \ 
              -e CONFIG_FILE_PATH=/work/sample/gunicorn.conf.py \   
              -e START_OPTION=sample.main:app \ 
              gunicorn:0.1
```

    
    
---
### **Configuration**

### Environment variables required
* START_OPTION  
    * This mean the full gunicorn cli command, including `APP_MODULE`.
    * However, if you want to set the configuration, I recommend using `gunicorn.conf.py` with the `CONFIG FILE PATH` option.

* REQUIRENMENTS_FILE_PATH
    * means `requirements.txt`

* CONFIG_FILE_PATH
    * means `gunicorn.conf.py` files path

All other environment variables are based on the following documentation.  
[Configuration Document](https://github.com/benoitc/gunicorn/blob/master/examples/example_config.py)


