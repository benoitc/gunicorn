# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

def patch_django():
    """ monkey patch django.

    This patch make sure that we use real threads to get the ident which
    is going to happen if we are using gevent or eventlet.
    """

    try:
        from django.db import DEFAULT_DB_ALIAS
        from django.db.backends import BaseDatabaseWrapper, DatabaseError

        if "validate_thread_sharing" in BaseDatabaseWrapper.__dict__:
            import thread
            _get_ident = thread.get_ident

            def _init(self, settings_dict, alias=DEFAULT_DB_ALIAS,
                    allow_thread_sharing=False):
                self.connection = None
                self.queries = []
                self.settings_dict = settings_dict
                self.alias = alias
                self.use_debug_cursor = None

                # Transaction related attributes
                self.transaction_state = []
                self.savepoint_state = 0
                self._dirty = None
                self._thread_ident = _get_ident()
                self.allow_thread_sharing = allow_thread_sharing


            def _validate_thread_sharing(self):
                if (not self.allow_thread_sharing
                    and self._thread_ident != _get_ident()):
                        raise DatabaseError("DatabaseWrapper objects created in a "
                            "thread can only be used in that same thread. The object "
                            "with alias '%s' was created in thread id %s and this is "
                            "thread id %s."
                            % (self.alias, self._thread_ident, _get_ident()))

            BaseDatabaseWrapper.__init__ = _init
            BaseDatabaseWrapper.validate_thread_sharing = _validate_thread_sharing

    except ImportError, e:
        pass

