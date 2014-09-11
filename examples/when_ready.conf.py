import signal
import commands
import threading
import time

max_mem = 100000

class MemoryWatch(threading.Thread):

    def __init__(self, server, max_mem):
        super(MemoryWatch, self).__init__()
        self.daemon = True
        self.server = server
        self.max_mem = max_mem
        self.timeout = server.timeout / 2

    def memory_usage(self, pid):
        try:
            out = commands.getoutput("ps -o rss -p %s" % pid)
        except IOError:
            return -1
        used_mem = sum(int(x) for x in out.split('\n')[1:])
        return used_mem

    def run(self):
        while True:
            for (pid, worker) in list(self.server.WORKERS.items()):
                if self.memory_usage(pid) > self.max_mem:
                    self.server.log.info("Pid %s killed (memory usage > %s)",
                        pid, self.max_mem)
                    self.server.kill_worker(pid, signal.SIGTERM)
            time.sleep(self.timeout)


def when_ready(server):
    mw = MemoryWatch(server, max_mem)
    mw.start()
