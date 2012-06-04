from multiprocessing import Process, Queue
import requests

def child_process(queue):
    while True:
        print queue.get()
        r = requests.get('http://friendpaste.com')
        print r.headers

class GunicornSubProcessTestMiddleware(object):
    def __init__(self):
        super(GunicornSubProcessTestMiddleware, self).__init__()
        self.queue = Queue()
        self.process = Process(target=child_process, args=(self.queue,))
        self.process.start()

    def process_request(self, request):
        self.queue.put(('REQUEST',))

    def process_response(self, request, response):
        self.queue.put(('RESPONSE',response.status_code))
        return response
