#!/bin/sh
cd "$(dirname "$0")/.." || exit 1
# 优先使用项目 .venv（与 run_web.sh 一致），其次回退到系统 python3。
if [ -x .venv/bin/python ]; then
  PYTHON=.venv/bin/python
else
  PYTHON=python3
fi
# 三组测试：工作台（tools/tests）、对话与项目核验引擎（tests）、面试引擎（interview_agent/tests）。
# 任何一组失败整体就失败，但三组都会跑完，方便一次看到全部问题。
status=0
"$PYTHON" -I -B -m unittest discover -s tools/tests -v || status=1
PYTHONPATH=. "$PYTHON" -B -m unittest discover -s tests || status=1
PYTHONPATH=. "$PYTHON" -B -m unittest discover -s interview_agent/tests || status=1
exit $status
