from production_settings import *
#  Depending on situation, it could be 'development_settings', etc
# from the imported files comes the values of variables below: DEBUG, BIND_PORT, WORKER_PROCCESS
#  or any other you need/want.

print "{'DEBUG': %s, 'BIND_PORT': %s, 'WORKER_PROCCESS': %s, }" % \
      (str(DEBUG), str(BIND_PORT), str(WORKER_PROCCESS))

