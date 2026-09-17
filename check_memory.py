"""事前チェック: `docker compose up` の前に実行し、Docker Desktopに割り当てられた
メモリがこのTTSサーバー(BERT + TTSモデル)を動かすのに十分かを確認する。

講習会等、参加者の端末スペックがバラバラな環境で、原因の分かりにくい
OOM Kill(クラッシュループ)を未然に防ぐためのもの。

使い方:
    pip install docker
    python3 check_memory.py && docker compose up -d --build
"""

import sys

# BERT(deberta-v2-large, float32) + TTSモデル1個(LOAD_MODELS=koharune-ami)を
# 安全に動かすための目安。実測ではモデルロード完了時点で2.5〜4GB程度使用する。
REQUIRED_GB = 8.0


def main() -> int:
    try:
        import docker
    except ImportError:
        print("エラー: 'docker' パッケージが見つかりません。次を実行してください:")
        print("    pip install docker")
        return 1

    try:
        client = docker.from_env()
        info = client.info()
    except Exception as e:
        print("エラー: Dockerデーモンに接続できませんでした。Docker Desktopが起動しているか確認してください。")
        print(f"詳細: {e}")
        return 1

    mem_total_gb = info["MemTotal"] / (1024**3)
    ncpu = info.get("NCPU", "不明")

    print(f"Docker Desktopの割り当てメモリ: {mem_total_gb:.1f} GB")
    print(f"Docker Desktopの割り当てCPU数: {ncpu}")

    if mem_total_gb < REQUIRED_GB:
        print()
        print(f"[NG] 推奨メモリ({REQUIRED_GB:.0f}GB以上)に対して割り当てが不足しています。")
        print("  このまま起動すると、モデルロード中にメモリ不足でコンテナが")
        print("  再起動を繰り返す(クラッシュループ)可能性があります。")
        print()
        print("  対処: Docker Desktop → Settings → Resources → Memory を増やし、")
        print(f"  {REQUIRED_GB:.0f}GB以上に設定してDocker Desktopを再起動してください。")
        print("  その後、もう一度このスクリプトを実行してください。")
        return 1

    print()
    print("[OK] メモリ割り当ては十分です。`docker compose up -d --build` を実行してください。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
