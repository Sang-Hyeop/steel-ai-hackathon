"""Rebuild unified wrench dataset; preserve deployed v2 until candidate is reviewed."""
from pathlib import Path
import subprocess,sys,json
ROOT=Path(__file__).resolve().parents[1]
def run(*args):subprocess.run([sys.executable,*map(str,args)],cwd=ROOT,check=True)
if __name__=='__main__':
 run(ROOT/'tools/prepare_aihub_v3.py')
 run(ROOT/'tools/crop_aihub_v3.py')
 data=ROOT/'data/processed/aihub_4class_crops_v3'
 records=json.loads((data/'manifest.json').read_text())
 groups={s:{Path(r['source_image']).stem for r in records if r['split']==s} for s in ['train','val','test']}
 for a,b in [('train','val'),('train','test'),('val','test')]:assert not groups[a]&groups[b], 'Source leakage'
 for f in (data/'labels').rglob('*.txt'):
  assert (data/'images'/f.parent.name/(f.stem+'.jpg')).exists()
  for line in f.read_text().splitlines():
   c,x,y,w,h=map(float,line.split());assert c in range(4) and 0<=x<=1 and 0<=y<=1 and 0<w<=1 and 0<h<=1
 print('V3_DATA_VALIDATED',flush=True)
 run(ROOT/'tools/train_tools.py','--data',data/'data.yaml','--epochs','5','--name','yolo11n_unified_wrench_v3','--skip-test')
 for weights,name in [(ROOT/'models/tools_yolo11n_v2.pt','v2_on_unified_v3_val'),(ROOT/'runs/yolo11n_unified_wrench_v3/weights/best.pt','v3_on_unified_v3_val')]:
  run(ROOT/'tools/evaluate_detector.py',weights,'--data',data,'--name',name)
 print('V3_TRAINING_AND_VALIDATION_COMPLETE',flush=True)
