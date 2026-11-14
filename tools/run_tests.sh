#!/bin/sh
cd "$(dirname "$0")/.." || exit 1
python3 -I -B -m unittest discover -s tools/tests -v
