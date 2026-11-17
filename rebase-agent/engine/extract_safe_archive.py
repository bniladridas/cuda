#!/usr/bin/env python3
"""Extract a source archive containing only regular files and directories."""

import argparse
import tarfile
from pathlib import PurePosixPath


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive")
    parser.add_argument("destination")
    args = parser.parse_args()
    with tarfile.open(args.archive) as archive:
        for member in archive.getmembers():
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts:
                raise SystemExit("unsafe path in source archive")
            if not (member.isfile() or member.isdir()):
                raise SystemExit("non-regular source archive entry rejected")
        archive.extractall(args.destination)


if __name__ == "__main__":
    main()
