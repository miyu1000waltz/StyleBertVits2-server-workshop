#!/bin/bash
set -e

MODEL_DIR="/app/model_assets"

# .safetensors ファイルが存在しない場合はモデルをダウンロードする
MODEL_COUNT=$(find "$MODEL_DIR" -name "*.safetensors" 2>/dev/null | wc -l)
if [ "$MODEL_COUNT" -eq 0 ]; then
    echo "[start.sh] No models found in ${MODEL_DIR}. Downloading..."
    cd /app && python download_models.py
fi

echo "[start.sh] Starting server on :8100..."
exec uvicorn main:app --host 0.0.0.0 --port 8100
