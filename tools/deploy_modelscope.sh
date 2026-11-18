#!/bin/sh
# 把当前 Git 已跟踪的文件推到魔搭创空间并触发部署。以后改了代码，重新运行本脚本即可更新。
#
# 用法：
#   export MODELSCOPE_API_KEY=你的魔搭访问令牌      # https://modelscope.cn/my/myaccesstoken
#   sh tools/deploy_modelscope.sh <魔搭用户名>/<创空间名> [--no-deploy]
#
# 只推送 git 已跟踪的文件（git archive HEAD）：.gitignore 里的个人数据、简历、凭据不会上传；
# 没提交的改动也不会上传，请先 git commit。令牌只在本进程与临时目录里使用，结束后删除。
set -eu

TARGET="${1:-}"
DEPLOY=1
[ "${2:-}" = "--no-deploy" ] && DEPLOY=0
case "$TARGET" in */*) ;; *) echo "用法: sh tools/deploy_modelscope.sh <用户名>/<创空间名> [--no-deploy]" >&2; exit 2;; esac
[ -n "${MODELSCOPE_API_KEY:-}" ] || { echo "请先 export MODELSCOPE_API_KEY=<令牌>" >&2; exit 2; }

ENDPOINT="${MODELSCOPE_ENDPOINT:-https://modelscope.cn}"
HOST="${ENDPOINT#https://}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

if ! git -C "$ROOT" diff --quiet HEAD -- . ; then
  echo "提示：有未提交的改动，它们不会被部署（只部署已提交内容）。" >&2
fi

git clone --quiet "https://oauth2:${MODELSCOPE_API_KEY}@${HOST}/studios/${TARGET}.git" "$WORK/repo"
cd "$WORK/repo"
# 清空工作区（保留 .git），再放入当前提交的全部跟踪文件。
find . -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
git -C "$ROOT" archive HEAD | tar -x -C .
git add -A
if git diff --cached --quiet; then
  echo "没有新的改动需要推送。"
else
  git -c user.name="offerpilot-deploy" -c user.email="deploy@localhost" \
    commit --quiet -m "deploy: $(git -C "$ROOT" log -1 --format='%h %s')"
  BRANCH="$(git rev-parse --abbrev-ref HEAD)"
  git push --quiet origin "$BRANCH"
  echo "已推送到 ${TARGET}（分支 ${BRANCH}）。"
fi

if [ "$DEPLOY" = 1 ]; then
  curl -fsS -X POST "${ENDPOINT}/openapi/v1/studios/${TARGET}/deploy" \
    -H "Authorization: Bearer ${MODELSCOPE_API_KEY}" >/dev/null && echo "已触发部署；构建日志在创空间页面「日志」查看。"
fi
