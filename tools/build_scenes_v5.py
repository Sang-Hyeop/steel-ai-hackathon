"""Build multi-tool tabletop scenes from existing crops. Diagnostic photos are never used."""
from __future__ import annotations

import json
import random
from collections import defaultdict
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'data/processed/aihub_4class_crops_v4'
OUT = ROOT / 'data/processed/aihub_4class_scenes_v5'
NAMES = ['screwdriver', 'wrench', 'pliers', 'hammer']
# Hammer is scarce in crop data; oversample it in synthetic scenes.
CLASS_WEIGHT = {0: 1.0, 1: 1.0, 2: 1.1, 3: 2.4}


def yolo_boxes(label_path: Path, width: int, height: int):
    boxes = []
    for line in label_path.read_text().splitlines():
        c, x, y, w, h = map(float, line.split())
        boxes.append((int(c), (x - w / 2) * width, (y - h / 2) * height, w * width, h * height))
    return boxes


def load_pool(split: str):
    pool = defaultdict(list)
    for image_path in sorted((SRC / 'images' / split).glob('*.jpg')):
        label_path = SRC / 'labels' / split / (image_path.stem + '.txt')
        if not label_path.exists():
            continue
        image = Image.open(image_path).convert('RGBA')
        boxes = yolo_boxes(label_path, *image.size)
        if not boxes:
            continue
        # Prefer mostly-single-class crops so pasted tools stay readable.
        classes = {c for c, *_ in boxes}
        if len(classes) != 1:
            continue
        cls = next(iter(classes))
        pool[cls].append((image, boxes))
    return pool


def canvas_bg(size: int, rng: random.Random):
    base = rng.randint(188, 228)
    image = Image.new('RGB', (size, size), (base, base - 4, base - 10))
    draw = ImageDraw.Draw(image)
    for _ in range(80):
        x, y = rng.randint(0, size - 1), rng.randint(0, size - 1)
        r = rng.randint(8, 40)
        shade = base + rng.randint(-18, 12)
        draw.ellipse((x - r, y - r, x + r, y + r), fill=(shade, shade - 3, shade - 8))
    return image.filter(ImageFilter.GaussianBlur(radius=1.2))


def paste_tool(scene, tool_rgba, boxes, x, y, scale, rng):
    w = max(16, int(tool_rgba.width * scale))
    h = max(16, int(tool_rgba.height * scale))
    resized = tool_rgba.resize((w, h), Image.Resampling.BICUBIC)
    if rng.random() < 0.5:
        resized = resized.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    angle = rng.choice([0, 0, 0, 90, 180, 270, rng.randint(-25, 25)])
    rotated = resized.rotate(angle, expand=True, resample=Image.Resampling.BICUBIC)
    # Approximate rotated boxes with the pasted footprint; enough for multi-tool scene learning.
    rw, rh = rotated.size
    if x + rw > scene.width or y + rh > scene.height:
        return []
    scene.paste(rotated.convert('RGB'), (x, y), rotated.split()[-1])
    classes = sorted({c for c, *_ in boxes})
    pad = 2
    return [(c, x + pad, y + pad, max(8, rw - 2 * pad), max(8, rh - 2 * pad)) for c in classes]


def sample_classes(rng, n):
    weights = [CLASS_WEIGHT[i] for i in range(4)]
    chosen = []
    available = list(range(4))
    for _ in range(n):
        w = [CLASS_WEIGHT[i] for i in available]
        pick = rng.choices(available, weights=w, k=1)[0]
        chosen.append(pick)
        if len(available) > 1 and rng.random() < 0.85:
            available = [i for i in available if i != pick]
    if rng.random() < 0.45 and 3 not in chosen and available:
        chosen[rng.randrange(len(chosen))] = 3
    return chosen


def write_split(pool, split: str, count: int, size: int, seed: int):
    rng = random.Random(seed)
    img_dir = OUT / 'images' / split
    lbl_dir = OUT / 'labels' / split
    img_dir.mkdir(parents=True, exist_ok=True)
    lbl_dir.mkdir(parents=True, exist_ok=True)
    records = []
    for i in range(count):
        scene = canvas_bg(size, rng)
        n_tools = rng.choice([2, 3, 3, 4, 4])
        classes = sample_classes(rng, n_tools)
        labels = []
        occupied = []
        for cls in classes:
            if not pool[cls]:
                continue
            tool, boxes = rng.choice(pool[cls])
            scale = rng.uniform(0.28, 0.62)
            for _ in range(12):
                tw = int(tool.width * scale)
                th = int(tool.height * scale)
                if tw >= size - 8 or th >= size - 8:
                    scale *= 0.85
                    continue
                x = rng.randint(4, size - tw - 4)
                y = rng.randint(4, size - th - 4)
                rect = (x, y, x + tw, y + th)
                if any(not (rect[2] <= o[0] or rect[0] >= o[2] or rect[3] <= o[1] or rect[1] >= o[3]) for o in occupied):
                    continue
                placed = paste_tool(scene, tool, boxes, x, y, scale, rng)
                if not placed:
                    continue
                for c, bx, by, bw, bh in placed:
                    labels.append(f'{c} {(bx + bw / 2) / size:.6f} {(by + bh / 2) / size:.6f} {bw / size:.6f} {bh / size:.6f}')
                occupied.append(rect)
                break
        if len(labels) < 2:
            continue
        name = f'scene_{split}_{i:04d}'
        scene.save(img_dir / f'{name}.jpg', quality=92)
        (lbl_dir / f'{name}.txt').write_text('\n'.join(labels) + '\n')
        records.append({'name': name, 'classes': classes, 'n': len(labels)})
    return records


def copy_original_train(limit_per_class=400):
    """Keep some real crops so the model does not forget close-up appearance."""
    rng = random.Random(7)
    pool = load_pool('train')
    img_dir = OUT / 'images' / 'train'
    lbl_dir = OUT / 'labels' / 'train'
    kept = []
    for cls, items in pool.items():
        sample = items if len(items) <= limit_per_class else rng.sample(items, limit_per_class)
        for idx, (image, boxes) in enumerate(sample):
            name = f'crop_c{cls}_{idx:04d}'
            rgb = image.convert('RGB')
            rgb.save(img_dir / f'{name}.jpg', quality=95)
            w, h = rgb.size
            lines = []
            for c, bx, by, bw, bh in boxes:
                lines.append(f'{c} {(bx + bw / 2) / w:.6f} {(by + bh / 2) / h:.6f} {bw / w:.6f} {bh / h:.6f}')
            (lbl_dir / f'{name}.txt').write_text('\n'.join(lines) + '\n')
            kept.append(name)
    return kept


if __name__ == '__main__':
    if OUT.exists():
        import shutil
        shutil.rmtree(OUT)
    train_pool = load_pool('train')
    assert all(train_pool[c] for c in range(4)), {c: len(train_pool[c]) for c in range(4)}
    # Fixed v3 val/test paths are referenced from data.yaml for comparable metrics.
    scene_records = write_split(train_pool, 'train', count=2400, size=640, seed=42)
    crop_names = copy_original_train()
    fixed = ROOT / 'data/processed/aihub_4class_crops_v3'
    (OUT / 'manifest.json').write_text(json.dumps({
        'scenes': len(scene_records),
        'crops_kept': len(crop_names),
        'class_weights': CLASS_WEIGHT,
        'note': 'Synthetic multi-tool scenes + subset of real crops. Diagnostic user photos excluded.',
    }, ensure_ascii=False, indent=2))
    (OUT / 'data.yaml').write_text(
        f'path: {OUT}\n'
        f'train: images/train\n'
        f'val: {fixed}/images/val\n'
        f'test: {fixed}/images/test\n'
        'names: [screwdriver, wrench, pliers, hammer]\n'
    )
    print({
        'pool': {NAMES[c]: len(train_pool[c]) for c in range(4)},
        'scenes': len(scene_records),
        'crops_kept': len(crop_names),
        'out': str(OUT),
    }, flush=True)
