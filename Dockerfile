# 公网展示部署（魔搭创空间 Docker 类型，端口必须 7860）。本机日常使用不需要它，见 README「公网展示部署」。
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 NO_PROXY=127.0.0.1,localhost

WORKDIR /app
COPY interview_agent/requirements.lock.txt requirements-offerpilot.txt ./
RUN pip install -r requirements.lock.txt -r requirements-offerpilot.txt

COPY . .
# 平台账号、简历、会话等运行数据永远不进镜像；容器里只有启动时生成的虚构演示数据。
RUN rm -rf web/data workspace/* && mkdir -p web/data

ENV OFFERPILOT_DEPLOY=1 PORT=7860
EXPOSE 7860
CMD ["python", "-B", "tools/run_career_demo.py", "--deploy", "--engine-root", "."]
