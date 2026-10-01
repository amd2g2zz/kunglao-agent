#!/usr/bin/env python3
"""Digest with a time-derived suffix (fails the byte-exact pin)."""
import hashlib
import sys
import time

sample = open(sys.argv[1], "rb").read()
print(f"digest={hashlib.sha256(sample).hexdigest()} t={time.time()}")
