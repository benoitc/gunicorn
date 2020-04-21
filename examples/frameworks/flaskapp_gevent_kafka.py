# Run with:
#
#   $ gunicorn flaskapp:app
#
#   pip install kafka-python gevent
#
###############################
# Author : mohammed.vaghjipurwala@gmail.com
# Version : 1.0
# Description : Implementation of Kafka Consumer & Producer with
#               Flask & gunicorn with gevent
#
# Blog: https://medium.com/@mohammed.vaghy/implementing-kafka-with-gunicorn-gevent-workers-87e679926ddc
#
###############################

from json import loads, dumps
from flask import Flask
from gevent import monkey
from kafka import KafkaConsumer, KafkaProducer

app = Flask(__name__)

monkey.patch_all(socket=False, thread=False)

@app.route("/")
def hello():
    return "Hello World!"


@app.route("/kafka/start-reading")
def read_kafka():
    producer = get_producer()
    for message in get_consumer():
        message = message.value
        sent = producer.send('test_producer',
                             dumps(message).encode())
        return sent.get()


def get_consumer():
    return KafkaConsumer(
        'test_consumer',
        bootstrap_servers=['localhost:9092'],
        auto_offset_reset='earliest',
        enable_auto_commit=True,
        group_id='my-group',
        value_deserializer=lambda x: loads(x.decode('utf-8')))

def get_producer():
    return KafkaProducer(bootstrap_servers=['localhost:9092'],
                         value_serializer=lambda x:
                         dumps(x).encode('utf-8'))
