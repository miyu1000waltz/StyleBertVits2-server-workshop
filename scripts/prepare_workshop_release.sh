#!/usr/bin/env bash
#
# prepare_workshop_release.sh
#
# 【経緯】
# 本プロジェクトを講習会向けに配布するにあたり、Gitのコミットログ（開発中の
# 試行錯誤や内部的なやり取りが残っている）を受講者に共有したくない、という
# 要望があった。対応案として以下の3つを検討した。
#
#   ①既存リポジトリ上でGit logを全削除する
#     -> `git checkout --orphan` や `.git`削除→再initなどで実現できるが、
#        reflogや他ブランチ・タグにコミットが残っていると完全には消えず、
#        `git gc --prune=now --aggressive` 等の追加処理が必要になる。
#        作業ミスで履歴の一部が残留するリスクがある。
#   ②ファイルだけを新しいディレクトリにコピーする（本スクリプトの方式）
#     -> `.git` を一切コピーしないため、原理的に旧履歴が紛れ込む余地がゼロ。
#        実装もシンプルで、確実性が高い。
#   ③サブリポジトリ/subtree等で切り分ける
#     -> 履歴の一部を保ったまま切り出す用途向けであり、
#        「履歴を丸ごと隠したい」という今回の目的には合わず、
#        手順が複雑になるだけでメリットが薄い。
#
# 上記の比較から、確実性を優先して②の方式を採用し、コピー処理をスクリプト化した。
#
# 【やること】
#   1. このリポジトリのファイルを、Gitの管理情報（.git）・秘密情報/キャッシュ
#      （.env, __pycache__, *.pyc など）・音声モデル本体（model_assets/配下）を
#      除いて、指定した配布用ディレクトリへコピーする。
#      音声モデルを配布物に含めない理由:
#        - ライセンス: モデルの再配布条件を踏まえずに済む（配布はHuggingFace側に任せる）
#        - サイズ: モデル本体は数百MB単位あり、配布物を不必要に肥大化させる
#      いずれにせよ start.sh が初回起動時に HuggingFace から自動ダウンロードする
#      ため、配布物に含めなくても利用者側の追加作業は発生しない。
#   2. コピー先で `git init` して初期コミットを1つだけ作る（過去の履歴は一切
#      引き継がれない）。
#
# 【使い方】
#   ./scripts/prepare_workshop_release.sh [配布先ディレクトリ]
#
#   配布先ディレクトリを省略した場合は、プロジェクトの1つ上の階層に
#   "<プロジェクト名>-workshop" という名前で作成する。
#
# 【注意】
#   - 実行後は、配布先ディレクトリの中身（設定ファイル等）に秘密情報が
#     混入していないか、必ず目視で確認すること。
#   - 既に配布先ディレクトリが存在する場合は上書きしないよう停止する。
#   - model_assets/ 配下の音声モデル本体は配布物に含まれない（意図的）。

set -euo pipefail

# プロジェクトルート（このスクリプトの1つ上の階層）を取得
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_NAME="$(basename "${SRC_DIR}")"

# コピー先ディレクトリ（引数省略時は SRC_DIR の隣に "-workshop" を付けて作成）
DEST_DIR_INPUT="${1:-${SRC_DIR}/../${PROJECT_NAME}-workshop}"
DEST_PARENT="$(cd "$(dirname "${DEST_DIR_INPUT}")" && pwd)"
DEST_DIR="${DEST_PARENT}/$(basename "${DEST_DIR_INPUT}")"

if [ -e "${DEST_DIR}" ]; then
  echo "エラー: コピー先 '${DEST_DIR}' は既に存在します。上書き事故を防ぐため処理を中止します。" >&2
  exit 1
fi

echo "コピー元: ${SRC_DIR}"
echo "コピー先: ${DEST_DIR}"

mkdir -p "${DEST_DIR}"

# .git（Git履歴）と秘密情報・キャッシュ類、音声モデル本体を除外してコピーする。
# .git を除外することが、旧履歴を一切引き継がせないための本質的なポイント。
# model_assets/ 配下はディレクトリ構造（.gitkeep）だけ残し、中身のモデルファイルは
# 除外する（ライセンス・サイズの観点。利用者側で初回起動時に自動ダウンロードされる）。
rsync -a \
  --exclude='.git' \
  --exclude='.env' \
  --exclude='__pycache__/' \
  --exclude='*.pyc' \
  --include='model_assets/' \
  --include='model_assets/.gitkeep' \
  --exclude='model_assets/*' \
  "${SRC_DIR}/" "${DEST_DIR}/"

# コピー先で新規にGit管理を開始する（初期コミット1つのみ、過去履歴なし）
(
  cd "${DEST_DIR}"
  git init -q
  git add .
  git commit -q -m "Initial commit for workshop distribution"
)

echo "完了しました。"
echo "音声モデル本体（model_assets 配下）はライセンス・サイズの観点から含めていません。"
echo "利用者側で docker compose up 時に初回自動ダウンロードされます。"
echo "配布前に、以下を必ず確認してください:"
echo "  - ${DEST_DIR} 配下に秘密情報（APIキー、認証情報等）が混入していないか"
