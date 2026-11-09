from pathlib import Path
import subprocess,sys,time,json
ROOT=Path(__file__).resolve().parents[1]
def run(*args):subprocess.run([sys.executable,*map(str,args)],cwd=ROOT,check=True)
if __name__=='__main__':
 log=Path(sys.argv[1])
 while True:
  text=log.read_text(errors='replace')
  if 'V3_TRAINING_AND_VALIDATION_COMPLETE' in text:break
  if 'Traceback (most recent call last)' in text:raise RuntimeError('V3 failed; v4 not started')
  time.sleep(15)
 run(ROOT/'tools/crop_aihub_v4.py')
 data=ROOT/'data/processed/aihub_4class_crops_v4'
 records=json.loads((data/'manifest.json').read_text())
 groups={s:{Path(r['source_image']).stem for r in records if r['split']==s} for s in ['train','val','test']}
 for a,b in [('train','val'),('train','test'),('val','test')]:assert not groups[a]&groups[b]
 for f in (data/'labels/train').glob('*.txt'):
  for line in f.read_text().splitlines():
   c,x,y,w,h=map(float,line.split());assert c in range(4) and 0<=x<=1 and 0<=y<=1 and 0<w<=1 and 0<h<=1
 fixed=ROOT/'data/processed/aihub_4class_crops_v3'
 (data/'data.yaml').write_text(f'path: {data}\ntrain: images/train\nval: {fixed}/images/val\ntest: {fixed}/images/test\nnames: [screwdriver, wrench, pliers, hammer]\n')
 run(ROOT/'tools/train_tools.py','--data',data/'data.yaml','--epochs','15','--name','yolo11n_scale_v4','--skip-test')
 weights=ROOT/'runs/yolo11n_scale_v4/weights/best.pt'
 run(ROOT/'tools/evaluate_detector.py',weights,'--data',fixed,'--name','v4_on_unified_v3_val')
 run(ROOT/'tools/check_user_photos.py',weights,'--name','user_photos_v4')
 print('V4_TRAINING_AND_VALIDATION_COMPLETE',flush=True)
