"""Compare resolutions and diagnose object/count errors on frozen public test set."""
from pathlib import Path
import json,collections,time
from PIL import Image,ImageDraw
from ultralytics import YOLO
ROOT=Path(__file__).resolve().parents[1];DATA=ROOT/'data/processed/aihub_4class_crops';OUT=ROOT/'runs/resolution_diagnosis';OUT.mkdir(parents=True,exist_ok=True)
model=YOLO(str(ROOT/'runs/yolo11n_baseline/weights/best.pt'))
def iou(a,b):
 x=max(0,min(a[2],b[2])-max(a[0],b[0]));y=max(0,min(a[3],b[3])-max(a[1],b[1]));inter=x*y
 return inter/ max(1e-9,(a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-inter)
allruns={}
for size in [320,640]:
 rows=[];stats=collections.Counter();per=collections.defaultdict(collections.Counter);start=time.time()
 for result in model.predict(source=str(DATA/'images/test'),imgsz=size,conf=.45,iou=.7,device='cpu',stream=True,verbose=False):
  f=Path(result.path);h,w=result.orig_shape;gt=[]
  for l in (DATA/'labels/test'/(f.stem+'.txt')).read_text().splitlines():
   c,x,y,bw,bh=map(float,l.split());gt.append({'class':int(c),'box':[(x-bw/2)*w,(y-bh/2)*h,(x+bw/2)*w,(y+bh/2)*h]})
  preds=[{'class':int(b.cls.item()),'box':b.xyxy[0].tolist(),'conf':float(b.conf.item())} for b in result.boxes]
  truth=collections.Counter(g['class'] for g in gt);pred=collections.Counter(b['class'] for b in preds);exact=truth==pred;stats['images']+=1;stats['exact']+=exact;multi=len(gt)>1;stats['multi']+=multi;stats['multi_exact']+=multi and exact
  # Greedy localization matching, independent of class, IoU >= .5.
  pairs=sorted([(iou(g['box'],b['box']),i,j) for i,g in enumerate(gt) for j,b in enumerate(preds)],reverse=True);mg=set();mp=set();errors=collections.Counter()
  for overlap,i,j in pairs:
   if overlap<.5:break
   if i in mg or j in mp:continue
   mg.add(i);mp.add(j)
   if gt[i]['class']==preds[j]['class']:errors['correct_objects']+=1
   else:errors['wrong_class']+=1
  errors['missed']=len(gt)-len(mg)
  for j,b in enumerate(preds):
   if j not in mp:
    if any(g['class']==b['class'] and iou(g['box'],b['box'])>=.5 for g in gt):errors['duplicate_candidates']+=1
    else:errors['other_false_positive']+=1
  clean=not any(v for k,v in errors.items() if k!='correct_objects')
  stats['all_objects_correct']+=clean;stats['multi_all_objects_correct']+=multi and clean
  stats.update(errors)
  for c in range(4):
   if truth[c]:per[c]['images']+=1;per[c]['correct_count_images']+=truth[c]==pred[c]
  rows.append({'image':f.name,'exact':exact,'multi':multi,'truth':gt,'pred':preds,'errors':dict(errors)})
 summary={'imgsz':size,'conf':.45,'iou':.7,'stats':dict(stats),'class_counts':dict(per),'seconds':time.time()-start}
 (OUT/f'eval_{size}.json').write_text(json.dumps({'summary':summary,'rows':rows},indent=2));allruns[size]=rows;print(json.dumps(summary),flush=True)
# Export matching examples with ground truth in green and predictions in red.
other={r['image']:r for r in allruns[640]};chosen=[]
for r in allruns[320]:
 if r['multi'] and r['exact'] and not other[r['image']]['exact']:chosen.append(r['image'])
for r in allruns[320]:
 if r['multi'] and not r['exact'] and r['image'] not in chosen:chosen.append(r['image'])
chosen=chosen[:8];sheet=Image.new('RGB',(1200,320*len(chosen)), 'white');draw=ImageDraw.Draw(sheet)
for row,name in enumerate(chosen):
 for col,size in enumerate([320,640]):
  r=next(r for r in allruns[size] if r['image']==name);im=Image.open(DATA/'images/test'/name).convert('RGB');d=ImageDraw.Draw(im)
  for g in r['truth']:d.rectangle(g['box'],outline='green',width=3);d.text(g['box'][:2],f"GT {g['class']}",fill='green')
  for b in r['pred']:d.rectangle(b['box'],outline='red',width=2);d.text((b['box'][0],b['box'][1]+14),f"P {b['class']} {b['conf']:.2f}",fill='red')
  im.thumbnail((590,280));sheet.paste(im,(col*600,row*320+35));draw.text((col*600+5,row*320+5),f"{size}px | exact={r['exact']} | {r['errors']}",fill='black')
sheet.save(OUT/'error_comparison.jpg');(OUT/'examples.json').write_text(json.dumps(chosen,indent=2))
