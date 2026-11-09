"""Final STBM detector selection. Used by local and QR/mobile launchers."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# Locked production weights after v2/v3/v4/v5 comparison.
# v5 scene fine-tune regressed on real photos and must not auto-replace this.
FINAL_MODEL_NAME = 'tools_yolo11n_v4.pt'
FINAL_IMGSZ = '640'
FINAL_CONF = '0.35'


def final_model_path() -> Path:
    return ROOT / 'models' / FINAL_MODEL_NAME


def apply_model_env(*, required: bool = True) -> Path | None:
    """Pin STBM_MODEL_* for app recognition. Returns the weights path or None."""
    path = final_model_path()
    if not path.is_file():
        if required:
            raise SystemExit(
                f'최종 모델이 없습니다: {path}\n'
                'models/tools_yolo11n_v4.pt 를 확인하세요.'
            )
        print('경고: 최종 AI 모델 파일이 없어 수동 입력만 사용할 수 있습니다.', flush=True)
        return None
    os.environ['STBM_MODEL_PATH'] = str(path)
    os.environ['STBM_MODEL_IMGSZ'] = os.environ.get('STBM_MODEL_IMGSZ', FINAL_IMGSZ)
    os.environ['STBM_MODEL_CONF'] = os.environ.get('STBM_MODEL_CONF', FINAL_CONF)
    print(
        'AI 최종 모델:',
        path.name,
        f"imgsz={os.environ['STBM_MODEL_IMGSZ']}",
        f"conf={os.environ['STBM_MODEL_CONF']}",
        flush=True,
    )
    return path
