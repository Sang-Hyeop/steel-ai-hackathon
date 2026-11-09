"""Explicitly configured, local object detector. Never substitutes sample results."""
import base64
import os
from pathlib import Path
from threading import Lock
import io

_lock=Lock()
_model=None
_path=None
ALIASES={
 'screwdriver':'드라이버','phillips screwdriver':'드라이버','flathead screwdriver':'드라이버',
 'wrench':'몽키 스패너','spanner':'몽키 스패너','adjustable wrench':'몽키 스패너','combination wrench':'몽키 스패너',
 'monkey wrench':'몽키 스패너','렌치':'몽키 스패너',
 'pliers':'펜치','plier':'펜치','combination pliers':'펜치','hammer':'망치',
 'claw hammer':'망치','ball-peen hammer':'망치',
 **{x:x for x in ['드라이버','몽키 스패너','펜치','망치']}}
COLORS={
 '드라이버':(37,99,235),
 '몽키 스패너':(220,38,38),
 '펜치':(217,119,6),
 '망치':(22,163,74),
}

def model_available():
 p=os.environ.get('STBM_MODEL_PATH','')
 return bool(p and Path(p).is_file())

def _area(box):
 x1,y1,x2,y2=box
 return max(0.0,x2-x1)*max(0.0,y2-y1)

def _inter(a,b):
 ax1,ay1,ax2,ay2=a; bx1,by1,bx2,by2=b
 ix1,iy1,ix2,iy2=max(ax1,bx1),max(ay1,by1),min(ax2,bx2),min(ay2,by2)
 return max(0.0,ix2-ix1)*max(0.0,iy2-iy1)

def _iou(a,b):
 inter=_inter(a,b)
 if inter<=0: return 0.0
 return inter/max(_area(a)+_area(b)-inter,1e-9)

def _ios(a,b):
 """Intersection over smaller box — catches partial duplicate on a larger tool."""
 inter=_inter(a,b)
 if inter<=0: return 0.0
 return inter/max(min(_area(a),_area(b)),1e-9)

def _overlaps(a,b,iou_thresh=0.3,ios_thresh=0.45):
 return _iou(a,b)>=iou_thresh or _ios(a,b)>=ios_thresh

def filter_detections(detections,close_conf=0.25):
 """Drop overlapping duplicates across classes.

 Prefer higher confidence. If scores are close, prefer the larger box so a
 partial wrong class (e.g. pliers on part of a wrench) loses to the fuller box.
 """
 kept=[]
 for det in sorted(detections,key=lambda d:-d['confidence']):
  replaced=False
  for i,other in enumerate(kept):
   if not _overlaps(det['box'],other['box']): continue
   if abs(det['confidence']-other['confidence'])<=close_conf:
    winner=det if _area(det['box'])>=_area(other['box']) else other
   else:
    winner=det if det['confidence']>other['confidence'] else other
   kept[i]=winner;replaced=True;break
  if not replaced: kept.append(det)
 return kept

def annotate_image(image,detections):
 """Draw final (filtered) boxes so the review UI matches counted tools."""
 from PIL import ImageDraw, ImageFont
 annotated=image.copy()
 draw=ImageDraw.Draw(annotated)
 # Scale stroke with image size so phone photos stay readable.
 stroke=max(2,min(annotated.width,annotated.height)//220)
 size=max(14,stroke*7)
 font=ImageFont.load_default();korean_font=False
 for candidate in (
  '/System/Library/Fonts/AppleSDGothicNeo.ttc',
  '/Library/Fonts/AppleGothic.ttf',
  '/usr/share/fonts/truetype/nanum/NanumGothic.ttf',
  '/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc',
  '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
  str(Path(__file__).resolve().parent/'static'/'fonts'/'NotoSansKR-Regular.otf'),
  '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
 ):
  try:
   font=ImageFont.truetype(candidate,size)
   korean_font='Gothic' in candidate or 'Nanum' in candidate or 'NotoSans' in candidate or 'CJK' in candidate
   break
  except OSError: continue
 latin={'드라이버':'Driver','몽키 스패너':'Monkey','펜치':'Pliers','망치':'Hammer'}
 for det in detections:
  x1,y1,x2,y2=[int(round(v)) for v in det['box']]
  color=COLORS.get(det['tool'],(37,99,235))
  draw.rectangle((x1,y1,x2,y2),outline=color,width=stroke)
  name=det['tool'] if korean_font else latin.get(det['tool'],det['tool'])
  label=f"{name} {det['confidence']:.0%}"
  try: tb=draw.textbbox((0,0),label,font=font);tw,th=tb[2]-tb[0],tb[3]-tb[1]
  except Exception: tw,th=len(label)*8,14
  ty=max(0,y1-th-stroke*2)
  draw.rectangle((x1,ty,x1+tw+stroke*2,ty+th+stroke*2),fill=color)
  draw.text((x1+stroke,ty+stroke),label,fill=(255,255,255),font=font)
 buf=io.BytesIO();annotated.save(buf,format='JPEG',quality=85,optimize=True)
 return 'data:image/jpeg;base64,'+base64.b64encode(buf.getvalue()).decode('ascii')

def recognize_image(raw):
 global _model,_path
 if not model_available():
  raise RuntimeError('공구 인식 모델이 아직 연결되지 않았습니다. 수동 입력으로 계속할 수 있습니다.')
 from PIL import Image, ImageOps, UnidentifiedImageError
 try:
  image=Image.open(io.BytesIO(raw));image.verify()
  image=ImageOps.exif_transpose(Image.open(io.BytesIO(raw))).convert('RGB')
  if image.width*image.height>20000000: raise ValueError('이미지 크기가 너무 큽니다.')
 except (UnidentifiedImageError,OSError,ImportError): raise ValueError('읽을 수 없는 이미지입니다. 다시 촬영하세요.')
 try:
  from ultralytics import YOLO
  with _lock:
   path=os.environ['STBM_MODEL_PATH']
   if _model is None or _path!=path: _model=YOLO(path);_path=path
   names=[str(v).strip().lower() for v in _model.names.values()]
   if not any(n in ALIASES for n in names):
    raise RuntimeError('이 모델에는 지원하는 공구 분류가 없습니다. 공구 전용 모델을 연결하세요.')
   try:
    imgsz=int(os.environ.get('STBM_MODEL_IMGSZ','640'))
   except ValueError:
    raise RuntimeError('AI 이미지 크기 설정은 정수여야 합니다.')
   if not 128<=imgsz<=2048: raise RuntimeError('AI 이미지 크기 설정은 128~2048 범위여야 합니다.')
   try:
    conf=float(os.environ.get('STBM_MODEL_CONF','0.35'))
   except ValueError:
    raise RuntimeError('AI 신뢰도 설정은 숫자여야 합니다.')
   if not 0.05<=conf<=0.95: raise RuntimeError('AI 신뢰도 설정은 0.05~0.95 범위여야 합니다.')
   result=_model.predict(image,imgsz=imgsz,conf=conf,verbose=False)[0]
  detections=[]
  if result.boxes is not None:
   for box in result.boxes:
    label=str(result.names[int(box.cls.item())]).strip().lower();tool=ALIASES.get(label)
    if tool:
     detections.append(dict(tool=tool,confidence=round(float(box.conf.item()),3),box=box.xyxy[0].tolist()))
  detections=filter_detections(detections)
  counts={}
  for det in detections: counts[det['tool']]=counts.get(det['tool'],0)+1
  return dict(items=counts,detections=detections,annotated_image=annotate_image(image,detections),source='model')
 except RuntimeError: raise
 except Exception as e: raise RuntimeError('AI 인식에 실패했습니다. 재시도하거나 수동으로 입력하세요.') from e
