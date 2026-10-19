FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.8.22 /uv /bin/uv
RUN uv pip install --system --no-cache modal==1.2.6
WORKDIR /app
COPY launcher.py launcher.html ./
ENV HOME=/tmp
USER 10101
CMD ["python3", "-u", "launcher.py"]
