#!/bin/sh
cd "$(dirname "$0")/.." || exit 1
# 优先使用项目 .venv（与 run_web.sh 一致），其次回退到系统 python3。
if [ -x .venv/bin/python ]; then
  PYTHON=.venv/bin/python
else
  PYTHON=python3
fi
exec "$PYTHON" -I -B -m unittest discover -s tools/tests -v
