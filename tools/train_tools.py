"""YOLO11n smoke/full training and held-out public-data evaluation."""
from pathlib import Path
import argparse,json,platform
from ultralytics import YOLO
import torch
ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--epochs',type=int,default=30);p.add_argument('--fraction',type=float,default=1);p.add_argument('--imgsz',type=int,default=320);p.add_argument('--name',default='yolo11n_aihub');p.add_argument('--skip-test',action='store_true');p.add_argument('--batch',type=int,default=16);p.add_argument('--threads',type=int,default=4);p.add_argument('--data',default=str(ROOT/'data/processed/aihub_4class_crops_v2/data.yaml'));a=p.parse_args()
if __name__=='__main__':
 torch.set_num_threads(a.threads)
 device='mps' if torch.backends.mps.is_available() else 'cpu'
 model=YOLO(str(ROOT/'models/yolo11n.pt'))
 model.train(data=a.data,epochs=a.epochs,fraction=a.fraction,imgsz=a.imgsz,batch=a.batch,device=device,workers=0,project=str(ROOT/'runs'),name=a.name,seed=42,deterministic=True,patience=10,plots=True,save=True)
 best=Path(model.trainer.best)
 if a.skip_test:
  print('Saved model (test evaluation skipped):',best);raise SystemExit(0)
 result=YOLO(str(best)).val(data=a.data,split='test',imgsz=a.imgsz,device=device,batch=a.batch,workers=0,project=str(ROOT/'runs'),name=a.name+'_public_test')
 (best.parent.parent/'public_test_metrics.json').write_text(json.dumps(result.results_dict,indent=2))
 print('Model:',best,'Device:',device)
