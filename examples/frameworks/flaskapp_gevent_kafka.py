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
from gevent import pool
from kafka import KafkaConsumer, KafkaProducer

APP = Flask(__name__)

WORKER_THREADS = 10
POOL = pool.Pool(WORKER_THREADS)

@APP.route("/")
def hello():
    """
    ########################################
    ## Method to flask app
    ########################################
    """
    return "Hello World!"


def get_status(green_thread):
    """
    ########################################
    ## Method to get the status of greenlet
    ########################################
    """
    total = 0
    running = 0
    completed = 0
    succeeded = 0
    yet_to_run = 0
    failed = 0
    total += 1
    if bool(green_thread):
        running += 1
    elif green_thread.ready():
        completed += 1
        if green_thread.successful():
            succeeded += 1
        else:
            failed += 1
    else:
        yet_to_run += 1

    return dict(total=total,
                running=running,
                completed=completed,
                succeeded=succeeded,
                yet_to_run=yet_to_run,
                failed=failed)

@APP.route("/kafka/start-reading")
def process_records():
    """
    ########################################
    ## Starter method to trigger the reader
    ## & producer method in async mode using
    ## greenlets
    ########################################
    """
    # Creating green threads(Greenlets)
    greenlet = POOL.apply_async(read_kafka)
    response = get_status(greenlet)
    print(response)
    while True:
        response = get_status(greenlet)
        print(response)
        if response['running'] == response['total']:
            break
        print("retrying...")
    return_str = "Greenlet started Successfully !"
    return return_str

def read_kafka():
    """
    ########################################
    ## Method to read data from topic and
    ## produce on another topic
    ########################################
    """
    producer = get_producer()
    for message in get_consumer():
        message = message.value
        sent = producer.send('test_producer',
                             message)
        return sent.get()


def get_consumer():
    """
    ########################################
    ## Method to generate consumer object
    ########################################
    """
    return KafkaConsumer(
        'test_consumer',
        bootstrap_servers=['localhost:9092'],
        auto_offset_reset='earliest',
        enable_auto_commit=True,
        group_id='my-group',
        value_deserializer=lambda x: loads(x.decode('utf-8')))

def get_producer():
    """
    ########################################
    ## Method to generate Producer object
    ########################################
    """
    return KafkaProducer(bootstrap_servers=['localhost:9092'],
                         value_serializer=lambda x:
                         dumps(x).encode('utf-8'))
