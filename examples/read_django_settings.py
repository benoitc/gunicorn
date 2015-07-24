# -*- coding: utf-8 -*-
#
import multiprocessing
import os
import sys
import ast
from subprocess import Popen, PIPE, CalledProcessError

SERVER_SOFTWARE = "Not Gunicorn"
log_level = "warning"
proc_name = "WebProject"
bind = "127.0.0.1:8001"
graceful_timeout = 10
timeout = 90
worker = 1

try:
    sys.path.append(os.path.join(os.path.abspath(os.path.dirname(__file__)), 'project_name'))
    script_file = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'project_name/settings.py')
    print script_file
    process = Popen(['python', script_file], stdout=PIPE)
    out, err = process.communicate()
    #  See 'project_name/settings.py' to see how variables come from Django's Settings
    try:
        dict_params = ast.literal_eval(out)
        if 'BIND_PORT' in dict_params:
            bind = "127.0.0.1:" + str(dict_params['BIND_PORT'])
            print u"\nBIND_PORT. Obtained: %s" % str(bind)
        if 'DEBUG' in dict_params:
            if bool(dict_params['DEBUG']):
                worker = 1
                log_level = 'debug'
                debug = True
                proc_name += "_debug"
        if 'WORKER_PROCCESS' in dict_params:
            if int(dict_params['WORKER_PROCCESS']) == 0:
                workers = multiprocessing.cpu_count() * 2 + 1
                print u"\nWORKER_PROCCESS. Calculated: %s proccess" % str(workers)
            else:
                workers = int(dict_params['WORKER_PROCCESS'])
                print u"\nWORKER_PROCCESS. Obtained: %s proccess" % str(workers)
    except ValueError:
        pass
except CalledProcessError:
    pass
