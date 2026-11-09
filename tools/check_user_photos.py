"""Diagnostic only: these photos must not enter training or independent test scores."""
from pathlib import Path
import argparse,json
from PIL import Image,ImageOps
import torch
from ultralytics import YOLO
ROOT=Path(__file__).resolve().parents[1]
if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('weights');parser.add_argument('--name',required=True);parser.add_argument('--imgsz',type=int,default=640);parser.add_argument('--conf',type=float,default=.35);args=parser.parse_args()
 torch.set_num_threads(2);model=YOLO(args.weights);data=ROOT/'data/diagnostic/user_photos';out=ROOT/'runs'/args.name;out.mkdir(parents=True,exist_ok=True);report=[]
 for case in json.loads((data/'cases.json').read_text()):
  im=ImageOps.exif_transpose(Image.open(data/case['image'])).convert('RGB');r=model.predict(im,imgsz=args.imgsz,conf=args.conf,verbose=False)[0]
  counts={n:sum(int(b.cls.item())==c for b in r.boxes) for c,n in model.names.items()}
  report.append({**case,'predicted':counts,'count_exact':counts==case['expected'],'detections':[{'class':r.names[int(b.cls.item())],'confidence':float(b.conf.item()),'box':b.xyxy[0].tolist()} for b in r.boxes]})
  preview=Image.fromarray(r.plot()[...,::-1]);preview.thumbnail((1200,1200));preview.save(out/(Path(case['image']).stem+'.jpg'))
 (out/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report,ensure_ascii=False),flush=True)
