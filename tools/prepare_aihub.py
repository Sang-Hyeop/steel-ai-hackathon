"""Prepare target AI-Hub classes, reserving original validation for public-only evaluation."""
from pathlib import Path
import zipfile,json,hashlib,random,collections,io
from PIL import Image,ImageOps
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'data/processed/aihub_4class'; OUT.mkdir(parents=True,exist_ok=True)
MAP={340:0,336:1,350:2,348:3}; NAMES=['screwdriver','wrench','pliers','hammer']
rng=random.Random(42); records=[]; seen=set(); counts=collections.Counter(); stats=collections.Counter()
raw=ROOT/'data/raw/aihub'
archives={p.name:p for p in raw.rglob('*.zip')}
image_zips=[zipfile.ZipFile(archives[n]) for n in ['TS_공구.zip','TS_공구02.zip','VS_공구.zip']]
index=[]
for z in image_zips:
 index.append({Path(n).stem:n for n in z.namelist() if n.lower().endswith('.jpg')})
# Test first: any exact duplicate encountered later is excluded from training.
for label_name,is_test in [('VL_공구.zip',True),('TL_공구.zip',False)]:
 with zipfile.ZipFile(archives[label_name]) as z:
  files=[n for n in z.namelist() if n.endswith('.json')];rng.shuffle(files)
  for n in files:
   d=json.loads(z.read(n)); anns=[a for a in d['annotations'] if a['category_id'] in MAP]
   if not anns:continue
   stem=Path(d['images'][0]['file_name']).stem
   zi=2 if is_test else next((i for i in [0,1] if stem in index[i]),-1)
   if zi<0 or stem not in index[zi]:stats['missing_image']+=1;continue
   im=ImageOps.exif_transpose(Image.open(io.BytesIO(image_zips[zi].read(index[zi][stem])))).convert('RGB')
   digest=hashlib.sha256(im.tobytes()).hexdigest()
   if digest in seen:stats['exact_duplicate_removed']+=1;continue
   seen.add(digest)
   # Stable filename grouping prevents same source filename leaking across splits.
   if not is_test and stem in test_stems:stats['same_name_excluded']+=1;continue
   split='test' if is_test else ('val' if int(hashlib.sha256(stem.encode()).hexdigest()[:8],16)%10==0 else 'train')
   w,h=im.size;lines=[]
   for a in anns:
    x,y,bw,bh=a['bbox'];x1=max(0,x);y1=max(0,y);x2=min(w,x+bw);y2=min(h,y+bh)
    if x2<=x1 or y2<=y1:stats['invalid_box']+=1;continue
    c=MAP[a['category_id']];lines.append(f'{c} {(x1+x2)/2/w:.8f} {(y1+y2)/2/h:.8f} {(x2-x1)/w:.8f} {(y2-y1)/h:.8f}');counts[f'{split}/{NAMES[c]}']+=1
   if not lines:continue
   for part in ['images','labels']:(OUT/part/split).mkdir(parents=True,exist_ok=True)
   name=digest[:24];im.thumbnail((1280,1280));im.save(OUT/'images'/split/(name+'.jpg'),quality=92)
   (OUT/'labels'/split/(name+'.txt')).write_text('\n'.join(lines)+'\n')
   records.append({'split':split,'name':name,'source_label':n,'source_archive':label_name,'source_image':index[zi][stem],'pixel_sha256':digest})
   stats[split]+=1
   if len(records)%200==0:print(dict(stats),flush=True)
 if is_test:test_stems={Path(r['source_image']).stem for r in records}
for z in image_zips:z.close()
(OUT/'data.yaml').write_text(f'path: {OUT}\ntrain: images/train\nval: images/val\ntest: images/test\nnames:\n'+''.join(f'  {i}: {v}\n' for i,v in enumerate(NAMES)))
(OUT/'manifest.json').write_text(json.dumps(records,ensure_ascii=False,indent=2))
(OUT/'summary.json').write_text(json.dumps({'images':dict(stats),'objects':dict(counts)},ensure_ascii=False,indent=2))
print('DONE',dict(stats),dict(counts),flush=True)
