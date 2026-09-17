from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # model_assets/ 以下のディレクトリ名。空文字の場合は最初に見つかったモデルを使用
    DEFAULT_MODEL_NAME: str = ""
    # カンマ区切りでロード対象のモデル名を限定する（メモリ節約用）。空文字なら従来通り全モデルをロードする
    LOAD_MODELS: str = ""
    # モデルロード時に確保しておく最低メモリ余裕(MB)。これを下回ったら以降のモデルロードをスキップする
    MIN_HEADROOM_MB: int = 1024
    DEFAULT_SPEAKER_ID: int = 0
    # スタイル名（モデルに存在しない場合は最初のスタイルにフォールバック）
    DEFAULT_STYLE: str = "Neutral"
    DEFAULT_STYLE_WEIGHT: float = 5.0
    # 話速（1.0が基準、大きいほど遅い）
    DEFAULT_LENGTH: float = 1.0
    DEFAULT_SDP_RATIO: float = 0.2
    DEFAULT_NOISE: float = 0.6
    DEFAULT_NOISEW: float = 0.8
    # デバイス: "cpu" または "cuda"
    DEVICE: str = "cpu"
    MODEL_DIR: str = "/app/model_assets"

    model_config = {"env_file": ".env"}


settings = Settings()
