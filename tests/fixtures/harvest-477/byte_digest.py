#!/usr/bin/env python3
"""Extract the digest line from the anchored sample."""
import hashlib
import sys

sample = open(sys.argv[1], "rb").read()
print(f"digest={hashlib.sha256(sample).hexdigest()}")
