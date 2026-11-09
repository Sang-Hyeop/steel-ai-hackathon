"""Fine-tune v4 on synthetic multi-tool scenes + crop subset, then evaluate."""
from pathlib import Path
import json
import subprocess
import sys

from ultralytics import YOLO
import torch

ROOT = Path(__file__).resolve().parents[1]


def run(*args):
    subprocess.run([sys.executable, *map(str, args)], cwd=ROOT, check=True)


if __name__ == '__main__':
    data = ROOT / 'data/processed/aihub_4class_scenes_v5/data.yaml'
    if not data.is_file():
        run(ROOT / 'tools/build_scenes_v5.py')
    assert data.is_file()
    weights = ROOT / 'models/tools_yolo11n_v4.pt'
    assert weights.is_file(), 'v4 weights missing'
    torch.set_num_threads(4)
    device = 'mps' if torch.backends.mps.is_available() else 'cpu'
    model = YOLO(str(weights))
    model.train(
        data=str(data),
        epochs=12,
        imgsz=640,
        batch=8,
        device=device,
        workers=0,
        project=str(ROOT / 'runs'),
        name='yolo11n_scene_v5',
        seed=42,
        deterministic=True,
        patience=8,
        plots=True,
        save=True,
        degrees=15.0,
        scale=0.6,
        shear=2.0,
        perspective=0.0003,
        mosaic=1.0,
        mixup=0.1,
        copy_paste=0.2,
        close_mosaic=5,
    )
    best = Path(model.trainer.best)
    fixed = ROOT / 'data/processed/aihub_4class_crops_v3'
    run(ROOT / 'tools/evaluate_detector.py', best, '--data', fixed, '--name', 'v5_on_unified_v3_val', '--imgsz', '640')
    run(ROOT / 'tools/check_user_photos.py', best, '--name', 'user_photos_v5', '--imgsz', '640', '--conf', '0.35')
    # Promote only after scripted checks; launcher still prefers explicit models/ file.
    target = ROOT / 'models/tools_yolo11n_v5.pt'
    target.write_bytes(best.read_bytes())
    report = {
        'weights': str(best),
        'promoted': str(target),
        'device': device,
        'imgsz': 640,
        'epochs': 12,
        'base': 'tools_yolo11n_v4.pt',
    }
    (ROOT / 'models/tools_yolo11n_v5.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print('V5_TRAINING_AND_VALIDATION_COMPLETE', report, flush=True)
