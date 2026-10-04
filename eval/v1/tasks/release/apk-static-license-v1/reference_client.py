#!/usr/bin/env python3
"""reference reimplementation (solvability proof; never staged)."""
import hashlib, json, sys

EXPECT = bytes.fromhex("88434c5435e01e14")


def verify(data: bytes) -> int:
    if len(data) < 16:
        return 1
    if len(data) > 127:
        return 2
    d = hashlib.sha256(data).digest()
    return 0 if bytes(b ^ 0xA5 for b in d[:8]) == EXPECT else 1


def main():
    case = sys.argv[1] if len(sys.argv) > 1 else "boundary"
    out = {"accept": verify(b"kunglao-v1-accept!!") == 0,
           "short": verify(b"tiny") == 1,
           "wrong": verify(b"X" * 16) == 1,
           "over": verify(b"A" * 200) == 2}
    print(json.dumps(out))
    sys.exit(0 if all(out.values()) else 1)


if __name__ == "__main__":
    main()
