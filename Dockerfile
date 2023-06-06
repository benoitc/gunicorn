FROM python:3.5-alpine

RUN pip install flask importlib_metadata==2.1.3

ADD . /gunicorn
WORKDIR /gunicorn
RUN python setup.py install

ADD ./examples/ourapp/ /app
WORKDIR /app
ENTRYPOINT ["gunicorn", "-c", "./gunicorn.py", "guniex.app:app"]
