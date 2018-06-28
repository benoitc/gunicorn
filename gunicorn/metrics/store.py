import time
import pickle
from collections import namedtuple

from gunicorn import six


class MetricsStore(object):
    Item = namedtuple('Item', ['metric_name', 'metric_type', 'tags', 'value'])

    def __init__(self, log):
        self.data = {}
        self.log = log

    def __getstate__(self):
        return self.data

    def __setstate__(self, state):
        self.data = state
        self.log = None

    def clear(self):
        self.data = {}

    def add(self, metric_name, metric_type, value, **tags):
        tags_hash = hash(frozenset(six.iteritems(tags)))
        self.data[metric_name, tags_hash] = (metric_type, value, tags)

    def add_worker(self, worker):
        try:
            stats = pickle.loads(worker.tmp.read())
        except EOFError:
            return
        except Exception:
            self.log.exception('Failed to load worker stats')
            return

        if stats.request_ended_at >= stats.request_started_at:
            # worker is not handling request now
            idle_time = time.time() - stats.request_ended_at
        else:
            # worker is handling a request now
            idle_time = 0

        idle_time_sum = stats.idle_time_sum + idle_time
        self.add('idle_time_seconds', 'gauge', idle_time, pid=worker.pid)
        self.add('idle_time_seconds_sum', 'summary', idle_time_sum, pid=worker.pid)

    def __iter__(self):
        for (metric_name, _), (metric_type, value, tags) in six.iteritems(self.data):
            yield self.Item(metric_name, metric_type, tags, value)

    def prometheus_iter(self):
        for item in self:
            tags_str = ','.join('{}="{}"'.format(*kv) for kv in six.iteritems(item.tags))
            if tags_str:
                tags_str = '{%s}' % tags_str

            yield '# TYPE {} {}'.format(item.metric_name, item.metric_type)
            yield '{}{} {}'.format(item.metric_name, tags_str, item.value)

    def prometheus_dump(self):
        return '\n'.join(line for line in self.prometheus_iter()).encode('utf-8') + b'\n'
