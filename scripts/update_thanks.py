#!/usr/bin/env python
# Usage: git log --format="%an <%ae>" | python update_thanks.py
# You will get a result.txt file, you can work with the file (update, remove, ...)
#
# Install
# =======
# pip install validate_email pyDNS
#
import sys

from validate_email import validate_email
from email.utils import parseaddr
import DNS.Base

addresses = set()
bad_addresses = set()
collection = []

lines = list(reversed(sys.stdin.readlines()))

for author in map(str.strip, lines):
    realname, email_address = parseaddr(author)

    if email_address not in addresses:
        if email_address in bad_addresses:
            continue
        else:
            try:
                value = validate_email(email_address)
                if value:
                    addresses.add(email_address)
                    collection.append(author)
                else:
                    bad_addresses.add(email_address)
            except DNS.Base.TimeoutError:
                bad_addresses.add(email_address)


with open('result.txt', 'w') as output:
    output.write('\n'.join(collection))
