"""デフォルト音声モデルを HuggingFace からダウンロードする。

ダウンロード先: ./model_assets/

使い方:
  pip install huggingface_hub
  python download_models.py            # 全モデル
  python download_models.py --models jvnv-F1-jp jvnv-F2-jp  # 指定モデルのみ
"""

import argparse
from pathlib import Path

from huggingface_hub import hf_hub_download

MODEL_DIR = Path("model_assets")

# 利用可能なデフォルトモデル一覧
MODELS = {
    "koharune-ami": {
        "repo_id": "litagin/sbv2_koharune_ami",
        "files": [
            "koharune-ami/config.json",
            "koharune-ami/koharune-ami.safetensors",
            "koharune-ami/style_vectors.npy",
        ],
    },
}


def download(model_name: str) -> None:
    entry = MODELS[model_name]
    repo_id = entry["repo_id"]
    for file in entry["files"]:
        dest = MODEL_DIR / file
        if dest.exists():
            print(f"  skip (already exists): {dest}")
            continue
        print(f"  downloading: {file}")
        hf_hub_download(repo_id, file, local_dir=MODEL_DIR)
    print(f"[OK] {model_name}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Download StyleBertVits2 voice models")
    parser.add_argument(
        "--models",
        nargs="+",
        choices=list(MODELS.keys()),
        default=list(MODELS.keys()),
        metavar="MODEL",
        help=f"ダウンロードするモデル名 (デフォルト: 全モデル)\n選択肢: {', '.join(MODELS.keys())}",
    )
    args = parser.parse_args()

    MODEL_DIR.mkdir(exist_ok=True)
    print(f"Download destination: {MODEL_DIR.resolve()}\n")

    for model_name in args.models:
        print(f"[{model_name}]")
        download(model_name)

    print("\nDone.")


if __name__ == "__main__":
    main()
