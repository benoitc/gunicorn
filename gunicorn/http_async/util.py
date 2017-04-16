# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

from collections import MutableMapping

class IOrderedDict(dict, MutableMapping):
    'Dictionary that remembers insertion order with insensitive key'
    # An inherited dict maps keys to values.
    # The inherited dict provides __getitem__, __len__, __contains__, and get.
    # The remaining methods are order-aware.
    # Big-O running times for all methods are the same as for regular dictionaries.

    # The internal self.__map dictionary maps keys to links in a doubly linked list.
    # The circular doubly linked list starts and ends with a sentinel element.
    # The sentinel element never gets deleted (this simplifies the algorithm).
    # Each link is stored as a list of length three:  [PREV, NEXT, KEY].

    def __init__(self, *args, **kwds):
        '''Initialize an ordered dictionary.  Signature is the same as for
        regular dictionaries, but keyword arguments are not recommended
        because their insertion order is arbitrary.

        '''
        if len(args) > 1:
            raise TypeError('expected at most 1 arguments, got %d' % len(args))
        try:
            self.__root
        except AttributeError:
            self.__root = root = [None, None, None]     # sentinel node
            PREV = 0
            NEXT = 1
            root[PREV] = root[NEXT] = root
            self.__map = {}
        self.__lower = {}
        self.update(*args, **kwds)

    def __setitem__(self, key, value, PREV=0, NEXT=1, dict_setitem=dict.__setitem__):
        'od.__setitem__(i, y) <==> od[i]=y'
        # Setting a new item creates a new link which goes at the end of the linked
        # list, and the inherited dictionary is updated with the new key/value pair.
        if key not in self:
            root = self.__root
            last = root[PREV]
            last[NEXT] = root[PREV] = self.__map[key] = [last, root, key]
            self.__lower[key.lower()] = key
        key = self.__lower[key.lower()]
        dict_setitem(self, key, value)

    def __delitem__(self, key, PREV=0, NEXT=1, dict_delitem=dict.__delitem__):
        'od.__delitem__(y) <==> del od[y]'
        # Deleting an existing item uses self.__map to find the link which is
        # then removed by updating the links in the predecessor and successor nodes.
        if key in self:
            key = self.__lower.pop(key.lower())

        dict_delitem(self, key)
        link = self.__map.pop(key)
        link_prev = link[PREV]
        link_next = link[NEXT]
        link_prev[NEXT] = link_next
        link_next[PREV] = link_prev

    def __getitem__(self, key, dict_getitem=dict.__getitem__):
        if key in self:
            key = self.__lower.get(key.lower())
        return dict_getitem(self, key)

    def __contains__(self, key):
        return key.lower() in self.__lower

    def __iter__(self, NEXT=1, KEY=2):
        'od.__iter__() <==> iter(od)'
        # Traverse the linked list in order.
        root = self.__root
        curr = root[NEXT]
        while curr is not root:
            yield curr[KEY]
            curr = curr[NEXT]

    def __reversed__(self, PREV=0, KEY=2):
        'od.__reversed__() <==> reversed(od)'
        # Traverse the linked list in reverse order.
        root = self.__root
        curr = root[PREV]
        while curr is not root:
            yield curr[KEY]
            curr = curr[PREV]

    def __reduce__(self):
        'Return state information for pickling'
        items = [[k, self[k]] for k in self]
        tmp = self.__map, self.__root
        del self.__map, self.__root
        inst_dict = vars(self).copy()
        self.__map, self.__root = tmp
        if inst_dict:
            return (self.__class__, (items,), inst_dict)
        return self.__class__, (items,)

    def clear(self):
        'od.clear() -> None.  Remove all items from od.'
        try:
            for node in self.__map.values():
                del node[:]
            self.__root[:] = [self.__root, self.__root, None]
            self.__map.clear()
        except AttributeError:
            pass
        dict.clear(self)

    def get(self, key, default=None):
        if key in self:
            return self[key]
        return default

    setdefault = MutableMapping.setdefault
    update = MutableMapping.update
    pop = MutableMapping.pop
    keys = MutableMapping.keys
    values = MutableMapping.values
    items = MutableMapping.items
    __ne__ = MutableMapping.__ne__

    def popitem(self, last=True):
        '''od.popitem() -> (k, v), return and remove a (key, value) pair.
        Pairs are returned in LIFO order if last is true or FIFO order if false.

        '''
        if not self:
            raise KeyError('dictionary is empty')
        key = next(reversed(self) if last else iter(self))
        value = self.pop(key)
        return key, value

    def __repr__(self):
        'od.__repr__() <==> repr(od)'
        if not self:
            return '%s()' % (self.__class__.__name__,)
        return '%s(%r)' % (self.__class__.__name__, list(self.items()))

    def copy(self):
        'od.copy() -> a shallow copy of od'
        return self.__class__(self)

    @classmethod
    def fromkeys(cls, iterable, value=None):
        '''OD.fromkeys(S[, v]) -> New ordered dictionary with keys from S
        and values equal to v (which defaults to None).

        '''
        d = cls()
        for key in iterable:
            d[key] = value
        return d

    def __eq__(self, other):
        '''od.__eq__(y) <==> od==y.  Comparison to another OD is order-sensitive
        while comparison to a regular mapping is order-insensitive.

        '''
        if isinstance(other, IOrderedDict):
            return len(self)==len(other) and \
                    set(self.items()) == set(other.items())
        return dict.__eq__(self, other)

    def __del__(self):
        self.clear()                # eliminate cyclical references
