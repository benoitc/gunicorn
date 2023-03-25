# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

import logging
import os
import tempfile

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, multiprocess

from gunicorn.glogging import BaseLogger, Logger


class Prometheus(Logger):
    """prometheus-based instrumentation, that passes as a logger
    """
    def __init__(self, cfg):
        super().__init__(cfg)

        self.prefix = cfg.prometheus_prefix.rstrip("_")

        fdir = cfg.worker_tmp_dir
        if fdir and not os.path.isdir(fdir):
            raise RuntimeError("%s doesn't exist. Can't create prometheustmp." % fdir)
        path = tempfile.mkdtemp(prefix="gunicorn-prometheus-", dir=fdir)

        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry, path=path)

        self.ERROR_COUNTER = Counter('gunicorn_error_total', 'How many warning, error, '
                                     'exception or critical logs occured',
                                     labelnames=['level'], registry=registry,
                                     namespace=self.prefix)
        self.REQUESTS_COUNTER = Counter('gunicorn_requests_total', 'How many HTTP requests '
                                        'processed, partitioned by status code and method.',
                                        labelnames=['code', 'method'], registry=registry,
                                        namespace=self.prefix)
        self.REQUESTS_HISTOGRAM = Histogram('gunicorn_request_duration_seconds', 'How long it '
                                            'took to process the request, partitioned by '
                                            'status code and method.',
                                            labelnames=['code', 'method'], registry=registry,
                                            namespace=self.prefix)
        self.WORKERS_GAUGE = Gauge('gunicorn_workers', 'How many active workers'
                                   ' processing requests',
                                   registry=registry, namespace=self.prefix)

        self.REGISTERED_METRICS = {
            (
                BaseLogger.WORKERS_COUNT_EXTRA['metric'],
                BaseLogger.WORKERS_COUNT_EXTRA['mtype']
            ): self.WORKERS_GAUGE,
        }

    # Log errors and warnings
    def critical(self, msg, *args, **kwargs):
        self.ERROR_COUNTER.labels(level='critical').inc()

    def error(self, msg, *args, **kwargs):
        self.ERROR_COUNTER.labels(level='error').inc()

    def warning(self, msg, *args, **kwargs):
        self.ERROR_COUNTER.labels(level='warning').inc()

    def exception(self, msg, *args, **kwargs):
        self.ERROR_COUNTER.labels(level='exception').inc()

    # Special treatment for info, the most common log level
    def info(self, msg, *args, **kwargs):
        self.log(logging.INFO, msg, *args, **kwargs)

    # skip the run-of-the-mill logs
    def debug(self, msg, *args, **kwargs):
        self.log(logging.DEBUG, msg, *args, **kwargs)

    def log(self, lvl, msg, *args, **kwargs):
        """Log a given statistic if metric, value and type are present
        """
        try:
            extra = kwargs.get("extra", None)
            if extra is not None:
                metric = extra.get(BaseLogger.METRIC_VAR, None)
                value = extra.get(BaseLogger.VALUE_VAR, None)
                typ = extra.get(BaseLogger.MTYPE_VAR, None)
                if metric and typ and value:
                    prometheus_metric = self.REGISTERED_METRICS.get((metric, typ))
                    if prometheus_metric:
                        if typ == BaseLogger.GAUGE_TYPE:
                            prometheus_metric.set(value)
                        elif typ == BaseLogger.COUNTER_TYPE:
                            prometheus_metric.inc(value)
                        elif typ == BaseLogger.HISTOGRAM_TYPE:
                            prometheus_metric.observe(value)
                        else:
                            pass
                    else:
                        super().warning(
                            'Unsupported metric name and type: {}, {}'.format(metric, typ)
                        )
        except Exception:
            super().warning("Failed capture log for prometheus", exc_info=True)

    # access logging
    def access(self, resp, req, environ, request_time):
        """Measure request duration
        request_time is a datetime.timedelta
        """
        duration_in_seconds = request_time.total_seconds()
        status = resp.status
        if isinstance(status, str):
            status = int(status.split(None, 1)[0])
        self.REQUESTS_COUNTER.labels(code=str(status), method=str(req.method)).inc()
        self.REQUESTS_HISTOGRAM.labels(code=str(status), method=str(req.method)) \
            .observe(duration_in_seconds)
