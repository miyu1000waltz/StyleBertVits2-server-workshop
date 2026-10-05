FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# pyopenjtalk などのネイティブ拡張のビルドに必要
RUN apt-get update && apt-get install -y \
    build-essential \
    cmake \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# numpy<2 を先にピン（torch が numpy 2.x を引き込む前に固定する）
# style-bert-vits2 の C 拡張 (pyworld 等) が numpy 1.x ABI でコンパイルされているため
RUN pip install --no-cache-dir "numpy<2"

# torch を先にインストールする（requirements.txt より前に入れて、種類とバージョンを固定する）
# - 既定は CPU 版（PyPI の既定では CUDA 版が入り、イメージが巨大になるため）
# - GPU 版は docker-compose.gpu.yml が TORCH_INDEX_URL を CUDA 版に差し替える（README の「GPU で動かす」）
ARG TORCH_VERSION=2.14.0
ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir "torch==${TORCH_VERSION}" --index-url "${TORCH_INDEX_URL}"

COPY server/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server/ .
COPY download_models.py .

COPY start.sh /start.sh
RUN chmod +x /start.sh

# 音声モデルはボリュームマウントで提供
VOLUME ["/app/model_assets"]

EXPOSE 8100

CMD ["/start.sh"]
