"""Evaluate class-count exact match at the web application's confidence threshold."""
from pathlib import Path
import argparse,json,collections
from ultralytics import YOLO
p=argparse.ArgumentParser();p.add_argument('weights');p.add_argument('--imgsz',type=int,default=640);a=p.parse_args();root=Path(__file__).resolve().parents[1];data=root/'data/processed/aihub_4class_crops';m=YOLO(a.weights);rows=[];exact=multi=multi_exact=0
for result in m.predict(source=str(data/'images/test'),imgsz=a.imgsz,conf=.45,device='cpu',stream=True,verbose=False):
 f=Path(result.path);truth=collections.Counter(int(l.split()[0]) for l in (data/'labels/test'/(f.stem+'.txt')).read_text().splitlines());pred=collections.Counter(int(x) for x in result.boxes.cls.tolist());ok=truth==pred;exact+=ok
 if sum(truth.values())>1:multi+=1;multi_exact+=ok
 rows.append({'image':f.name,'true':dict(truth),'predicted':dict(pred),'exact':ok})
out=Path(a.weights).resolve().parent.parent/'count_evaluation.json';out.write_text(json.dumps({'confidence':.45,'image_size':a.imgsz,'images':len(rows),'exact_count_images':exact,'exact_count_rate':exact/len(rows),'multi_tool_images':multi,'multi_tool_exact':multi_exact,'scope':'AI-Hub held-out context crops; not real phone photos','rows':rows},indent=2));print(out)
