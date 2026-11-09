"""Context crops from original resolution, preserving split provenance and all target boxes."""
from pathlib import Path
import json,zipfile,io,hashlib,collections
from PIL import Image,ImageOps
ROOT=Path(__file__).resolve().parents[1];src=ROOT/'data/processed/aihub_4class_v2';out=ROOT/'data/processed/aihub_4class_crops_v2';out.mkdir(parents=True,exist_ok=True)
archives={p.name:p for p in (ROOT/'data/raw/aihub').rglob('*.zip')};zs={n:zipfile.ZipFile(p) for n,p in archives.items()};mapping={340:0,336:1,350:2,348:3};records=[];seen=[];stats=collections.Counter()
def dhash(im):
 p=list(im.convert('L').resize((9,8)).getdata());return sum((p[y*9+x]>p[y*9+x+1])<<(y*8+x) for y in range(8) for x in range(8))
quarantine=json.loads((ROOT/'data/label_quarantine.json').read_text())
for rec in json.loads((src/'manifest.json').read_text()):
 if Path(rec['source_image']).stem in quarantine:stats['quarantined_source']+=1;continue
 d=json.loads(zs[rec['source_archive']].read(rec['source_label']));ann=[a for a in d['annotations'] if a['category_id'] in mapping];zn='VS_공구.zip' if rec['split']=='test' else ('TS_공구02.zip' if '/02/' in rec['source_image'] else 'TS_공구.zip');raw_image=Image.open(io.BytesIO(zs[zn].read(rec['source_image'])));orientation=raw_image.getexif().get(274,1);stats[f'source_orientation_{orientation}']+=1;im=ImageOps.exif_transpose(raw_image).convert('RGB');w,h=im.size
 for j,a in enumerate(ann):
  x,y,bw,bh=a['bbox'];side=max(bw,bh)*4;left=max(0,int(x+bw/2-side/2));top=max(0,int(y+bh/2-side/2));right=min(w,int(x+bw/2+side/2));bottom=min(h,int(y+bh/2+side/2));cw=right-left;ch=bottom-top
  if min(cw,ch)<16:continue
  crop=im.crop((left,top,right,bottom));ph=dhash(crop)
  # Similar crops always stay in the earlier split (test processed first).
  if any((ph-old).bit_length()==0 or (ph^old).bit_count()<=6 for old in seen):stats['similar_crop_excluded']+=1;continue
  lines=[];partial=False
  for b in ann:
   xx,yy,ww,hh=b['bbox'];ix=max(0,min(right,xx+ww)-max(left,xx));iy=max(0,min(bottom,yy+hh)-max(top,yy))
   if ix*iy==0:continue
   if ix*iy < ww*hh*.98:partial=True;break
   lines.append(f"{mapping[b['category_id']]} {(xx+ww/2-left)/cw:.8f} {(yy+hh/2-top)/ch:.8f} {ww/cw:.8f} {hh/ch:.8f}")
  if partial or not lines:stats['partial_excluded']+=1;continue
  seen.append(ph);split=rec['split'];name=rec['name']+f'_{j}'
  for part in ['images','labels']:(out/part/split).mkdir(parents=True,exist_ok=True)
  crop.thumbnail((640,640));crop.save(out/'images'/split/(name+'.jpg'),quality=95);(out/'labels'/split/(name+'.txt')).write_text('\n'.join(lines)+'\n');records.append({**rec,'crop_name':name,'crop_xyxy':[left,top,right,bottom],'dhash':str(ph),'source_exif_orientation':orientation});stats[split]+=1
for z in zs.values():z.close()
(out/'manifest.json').write_text(json.dumps(records,ensure_ascii=False,indent=2));(out/'summary.json').write_text(json.dumps(dict(stats),indent=2));(out/'data.yaml').write_text(f'path: {out}\ntrain: images/train\nval: images/val\ntest: images/test\nnames: [screwdriver, wrench, pliers, hammer]\n');print(dict(stats),flush=True)
