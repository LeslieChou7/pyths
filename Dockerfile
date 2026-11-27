# 实施时以 --build-arg PYTHON_IMAGE=python@sha256:... 固定已验证镜像。
ARG PYTHON_IMAGE=python:3.13-slim
FROM ${PYTHON_IMAGE} AS check
WORKDIR /sdk
COPY pyproject.toml README.md ./
COPY LICENSE NOTICE THIRD_PARTY_NOTICES.md ./
COPY src ./src
RUN python -m pip install --no-cache-dir '.[dev]'
COPY tests ./tests
COPY tools/check.py tools/validate_live.py ./tools/
COPY examples/*.py ./examples/
# Windows 构建上下文会把普通 Python 文件映射为可执行；恢复 Git 中的普通文件语义。
RUN find src tests tools examples -type f -name '*.py' -exec chmod 0644 {} +
ENV PYTHONDONTWRITEBYTECODE=1
CMD ["python", "tools/check.py"]

FROM ${PYTHON_IMAGE} AS runtime
COPY dist/*.whl /wheel/
RUN python -m pip install --no-index --no-deps /wheel/*.whl
COPY tools/validate_live.py /validation/validate_live.py
WORKDIR /run
ENV PYTHONDONTWRITEBYTECODE=1
ENTRYPOINT ["python", "-I", "/validation/validate_live.py"]
