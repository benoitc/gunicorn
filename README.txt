gunicorn 'Green Unicorn' is a WSGI HTTP Server for UNIX, fast clients and nothing else. 
This is a  port of Unicorn (http://unicorn.bogomips.org/) in Python.


Install
-------

Run command :
   
	$ python setup.py install


Use gunicorn:
-------------

	$ gunicorn --help
	Usage: gunicorn [OPTIONS] APP_MODULE

	Options:
	  --host=HOST        Host to listen on. [127.0.0.1]
	  --port=PORT        Port to listen on. [8000]
	  --workers=WORKERS  Number of workers to spawn. [1]
	  -h, --help         show this help message and exit


Example with test app :

	$ cd examples
	$ gunicorn --workers=2 test:app
	
	
For django projects use the `gunicorn_django` command.

	$ cd yourdjangoproject
	$ gunicorn_django --workers=2
	
	



