"""StyleBertVits2 TTSサーバー

coeiroink-server 互換インターフェース:
  POST /synthesize {"msg": "..."} → WAV (audio/wav)
"""

import logging
import sys
import time
from contextlib import asynccontextmanager
from io import BytesIO
from pathlib import Path
from typing import Optional

import torch
from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from pydantic import BaseModel
from scipy.io import wavfile

from config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)

_models: list = []
_model_dir = Path(settings.MODEL_DIR)


def _model_name(model) -> str:
    return Path(model.model_path).parent.name


def _cgroup_memory_max() -> Optional[int]:
    """cgroup v2の自コンテナメモリ上限(バイト)。docker run --memory等で明示指定していなければNone。"""
    try:
        val = Path("/sys/fs/cgroup/memory.max").read_text().strip()
    except OSError:
        return None
    return None if val == "max" else int(val)


def _cgroup_memory_current() -> Optional[int]:
    """cgroup v2の自コンテナ現在メモリ使用量(バイト)。"""
    try:
        return int(Path("/sys/fs/cgroup/memory.current").read_text().strip())
    except OSError:
        return None


def _vm_available_bytes() -> Optional[int]:
    """/proc/meminfoのMemAvailable。コンテナのcgroup制限を反映しないVM(ホスト)全体の値。"""
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) * 1024
    except OSError:
        pass
    return None


def _available_memory_bytes() -> Optional[int]:
    """モデルロード判断に使う「実質使える見込みのメモリ」。
    docker-compose等でコンテナに明示的なメモリ上限(mem_limit)を設定している場合は
    cgroupの残り(上限-使用中)を優先する。上限が未設定(本プロジェクトの現状の運用)の場合は、
    実質の制約がVM(Docker Desktop)全体のメモリになるため、/proc/meminfoのMemAvailableに
    フォールバックする。詳細: Linuxカーネル は/proc/meminfoをcgroup単位に仮想化しないため、
    上限が明示されていない限りコンテナ内から見えるのは常にVM全体の値になる。
    """
    limit = _cgroup_memory_max()
    if limit is not None:
        current = _cgroup_memory_current()
        if current is not None:
            return max(limit - current, 0)
    return _vm_available_bytes()


def _init_models() -> None:
    from style_bert_vits2.constants import Languages
    from style_bert_vits2.nlp import bert_models
    from style_bert_vits2.nlp.japanese.user_dict import update_dict
    from style_bert_vits2.tts_model import TTSModel, TTSModelHolder

    # NOTE: 2026/06/24 update_dict(): デフォルト辞書（pyopenjtalk に同梱された一般的な日本語読み辞書）とユーザー辞書（固有名詞など読みを独自登録した辞書）を結合して CSV を生成し、OpenJTalk 用にコンパイルして pyopenjtalk に反映する。
    # WARNING: 2026/06/24 initialize_worker(): pyopenjtalk を別プロセス（TCPワーカー）で動かし、ユーザー辞書への並列アクセスエラーを防ぐ仕組み は呼んではいけない。 pip install 環境では os.path.relpath でモジュールパスの計算が壊れ、ワーカー起動に失敗する。呼ばなければ WORKER_CLIENT=None のままpyopenjtalk が直接呼ばれるフォールバックパスが使われるため省略する。
    update_dict()

    # NOTE: 2026/06/24 HuggingFace リポジトリ名を明示指定してダウンロード/キャッシュを使う
    # HuggingFace 上の BERT モデルは float16 で保存されているため、
    # CPU 推論で TTS モデル（float32）との型不一致が起きる。
    # .float() で float32 にキャストしてから使う。
    logger.info("Loading BERT model (JP)...")
    bert_models.load_model(Languages.JP, "ku-nlp/deberta-v2-large-japanese-char-wwm").float()
    bert_models.load_tokenizer(Languages.JP, "ku-nlp/deberta-v2-large-japanese-char-wwm")
    logger.info("BERT model loaded.")

    if not _model_dir.exists():
        logger.error("MODEL_DIR not found: %s", _model_dir)
        sys.exit(1)

    device = "cuda" if settings.DEVICE == "cuda" and torch.cuda.is_available() else "cpu"
    logger.info("Device: %s", device)

    holder = TTSModelHolder(_model_dir, device)
    if not holder.model_names:
        logger.error("No models found in %s", _model_dir)
        sys.exit(1)

    # メモリ節約のため、LOAD_MODELS が指定されている場合はロード対象をそのモデル名だけに絞る。
    # 空文字なら従来通り model_assets/ 以下で見つかった全モデルをロードする。
    load_targets = {n.strip() for n in settings.LOAD_MODELS.split(",") if n.strip()}

    # NOTE: TTSModelHolder.model_files_dict は dir.iterdir() 由来でソートされておらず、
    # 複数チェックポイント（例: model_e100_s1000.safetensors, model_e200_s2000.safetensors）が
    # 同一フォルダにある場合 model_paths[0] は起動ごとに不定になりうる。
    # mtime が最も新しいものを決定的に選ぶ。モデル名側もソートして登録順を固定する。
    min_headroom_bytes = settings.MIN_HEADROOM_MB * 1024 * 1024
    for model_name in sorted(holder.model_files_dict.keys()):
        if load_targets and model_name not in load_targets:
            logger.info("Skip loading %s (not in LOAD_MODELS=%s)", model_name, settings.LOAD_MODELS)
            continue

        # 段階的デグレード: 既に1つ以上ロード済みで、かつ残りメモリがしきい値を下回る場合、
        # それ以降のモデルロードをスキップする(1つも読めずに起動失敗するよりはマシ、という判断)。
        available = _available_memory_bytes()
        if _models and available is not None and available < min_headroom_bytes:
            logger.warning(
                "Skip loading %s: available memory %.0fMB < MIN_HEADROOM_MB=%dMB",
                model_name, available / 1024**2, settings.MIN_HEADROOM_MB,
            )
            continue

        model_paths = holder.model_files_dict[model_name]
        model_path = max(model_paths, key=lambda p: p.stat().st_mtime)
        if len(model_paths) > 1:
            logger.warning(
                "Multiple checkpoints found for %s, using newest: %s",
                model_name, model_path.name,
            )
        model = TTSModel(
            model_path=model_path,
            config_path=_model_dir / model_name / "config.json",
            style_vec_path=_model_dir / model_name / "style_vectors.npy",
            device=device,
        )
        # 明示的にロードしておく。呼ばないと初回 /synthesize リクエスト時に
        # 遅延ロードされ、/health が ready を返していても最初の1回だけ大きく遅延する。
        model.load()
        _models.append(model)
        logger.info("Registered model: %s (speakers=%s, styles=%s)", model_name, list(model.spk2id.keys()), list(model.style2id.keys()))

    if not _models:
        logger.error("LOAD_MODELS=%r matched no model in %s", settings.LOAD_MODELS, _model_dir)
        sys.exit(1)


def _resolve_model(model_name: Optional[str]):
    if not _models:
        raise HTTPException(status_code=503, detail="Models not loaded")
    if model_name:
        for m in _models:
            if _model_name(m) == model_name:
                return m
        raise HTTPException(status_code=404, detail=f"Model not found: {model_name}")
    if settings.DEFAULT_MODEL_NAME:
        for m in _models:
            if _model_name(m) == settings.DEFAULT_MODEL_NAME:
                return m
        logger.warning("DEFAULT_MODEL_NAME=%r not found, using first model", settings.DEFAULT_MODEL_NAME)
    return _models[0]


@asynccontextmanager
async def lifespan(app: FastAPI):
    _init_models()
    yield


app = FastAPI(title="StyleBertVits2 Server", lifespan=lifespan)


class SynthesizeRequest(BaseModel):
    msg: str
    model_name: Optional[str] = None
    speaker_id: Optional[int] = None
    style: Optional[str] = None
    style_weight: Optional[float] = None
    length: Optional[float] = None


@app.post("/synthesize")
async def synthesize(req: SynthesizeRequest) -> Response:
    from style_bert_vits2.constants import Languages

    if not req.msg or not req.msg.strip():
        raise HTTPException(status_code=400, detail="msg must not be empty")

    model = _resolve_model(req.model_name)
    speaker_id = req.speaker_id if req.speaker_id is not None else settings.DEFAULT_SPEAKER_ID
    style = req.style or settings.DEFAULT_STYLE
    style_weight = req.style_weight if req.style_weight is not None else settings.DEFAULT_STYLE_WEIGHT
    length = req.length if req.length is not None else settings.DEFAULT_LENGTH

    if style not in model.style2id:
        style = next(iter(model.style2id))
        logger.warning("Requested style not found, falling back to %r", style)

    received_at = time.perf_counter()
    logger.info("[timing] synthesize request received: msg=%r model=%s", req.msg[:40], _model_name(model))

    try:
        # model.infer() は同期・CPU/GPUバウンドの重い処理。そのまま await 内で直接呼ぶと
        # イベントループ上で実行され、推論中は他の全リクエスト（/health含む）がブロックされる。
        # run_in_threadpool でスレッドプールに逃がし、イベントループを塞がないようにする。
        # ただしスレッドプールのワーカー数には限りがあるため、先行リクエストの推論が
        # 長引くと後続はここで「投入待ち」になる。dispatch_wait でその待ち時間を計測する。
        dispatch_start = time.perf_counter()
        sr, audio = await run_in_threadpool(
            model.infer,
            text=req.msg,
            language=Languages.JP,
            speaker_id=speaker_id,
            style=style,
            style_weight=style_weight,
            length=length,
            sdp_ratio=settings.DEFAULT_SDP_RATIO,
            noise=settings.DEFAULT_NOISE,
            noise_w=settings.DEFAULT_NOISEW,
            line_split=True,
            split_interval=0.5,
        )
        logger.info(
            "[timing] run_in_threadpool (dispatch+infer): %.3fs",
            time.perf_counter() - dispatch_start,
        )
    except Exception as e:
        logger.error(
            "Inference error after %.3fs: %s",
            time.perf_counter() - received_at, e,
        )
        raise HTTPException(status_code=500, detail=str(e))

    logger.info(
        "synthesize OK: msg=%r model=%s total=%.3fs",
        req.msg[:40], _model_name(model), time.perf_counter() - received_at,
    )
    with BytesIO() as buf:
        wavfile.write(buf, sr, audio)
        return Response(content=buf.getvalue(), media_type="audio/wav")


@app.get("/models")
def get_models():
    return [
        {
            "model_id": i,
            "model_name": _model_name(m),
            "speakers": m.spk2id,
            "styles": list(m.style2id.keys()),
        }
        for i, m in enumerate(_models)
    ]


@app.get("/health")
def health():
    return {
        "status": "ok" if _models else "no_models",
        "models": len(_models),
        "loaded_models": [_model_name(m) for m in _models],
        "memory": {
            "cgroup_limit_bytes": _cgroup_memory_max(),
            "cgroup_current_bytes": _cgroup_memory_current(),
            "available_bytes": _available_memory_bytes(),
        },
    }
