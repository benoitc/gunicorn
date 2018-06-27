import time


class WorkerStats(object):
    def __init__(self):
        self.idle_time_sum = 0
        self.request_started_at = time.time()
        self.request_ended_at = time.time()

    def start_request(self):
        self.request_started_at = time.time()
        self.idle_time_sum += self.request_started_at - self.request_ended_at

    def end_request(self):
        self.request_ended_at = time.time()
