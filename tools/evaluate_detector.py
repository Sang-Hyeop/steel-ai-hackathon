"""Evaluate frozen model on validation data; no test-driven parameter search."""
from pathlib import Path
import argparse,json,collections
import torch
from ultralytics import YOLO
p=argparse.ArgumentParser();p.add_argument('weights');p.add_argument('--data',required=True);p.add_argument('--name',required=True);p.add_argument('--imgsz',type=int,default=320);a=p.parse_args();torch.set_num_threads(4)
root=Path(__file__).resolve().parents[1];data=Path(a.data);out=root/'runs'/a.name;out.mkdir(parents=True,exist_ok=True);model=YOLO(a.weights)
metric=model.val(data=str(data/'data.yaml'),split='val',imgsz=a.imgsz,device='cpu',batch=16,workers=0,project=str(out),name='detection',plots=True)
rows=[];exact=multi=multi_exact=0
for r in model.predict(source=str(data/'images/val'),imgsz=a.imgsz,conf=.45,iou=.7,device='cpu',stream=True,verbose=False):
 f=Path(r.path);truth=collections.Counter(int(l.split()[0]) for l in (data/'labels/val'/(f.stem+'.txt')).read_text().splitlines());pred=collections.Counter(int(c) for c in r.boxes.cls.tolist());ok=truth==pred;exact+=ok
 if sum(truth.values())>1:multi+=1;multi_exact+=ok
 rows.append({'image':f.name,'truth':dict(truth),'predicted':dict(pred),'exact':ok})
d={'split':'val','data':str(data),'weights':a.weights,'imgsz':a.imgsz,'confidence':.45,'iou':.7,'metrics':metric.results_dict,'count_images':len(rows),'count_exact':exact,'count_rate':exact/len(rows),'multi_images':multi,'multi_exact':multi_exact,'rows':rows};(out/'metrics.json').write_text(json.dumps(d,indent=2));print(json.dumps({k:v for k,v in d.items() if k!='rows'}),flush=True)
