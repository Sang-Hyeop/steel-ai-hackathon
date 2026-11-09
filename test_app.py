import unittest, tempfile, sqlite3, uuid, base64, io
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from app import create_app

def test_photo_data(color='red'):
 from PIL import Image
 buf=io.BytesIO();Image.new('RGB',(20,20),color).save(buf,'JPEG')
 return 'data:image/jpeg;base64,'+base64.b64encode(buf.getvalue()).decode()

class AppTest(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'test.sqlite3';self.app=create_app(self.path);self.app.testing=True
  self.admin=self.login('관리자');self.worker=self.login('김상협')
 def tearDown(self):self.tmp.cleanup()
 def login(self,name):
  c=self.app.test_client();r=c.post('/api/login',json={'name':name,'password':'1234'},headers={'X-STBM-Request':'1'});self.assertEqual(r.status_code,200);c.csrf=r.json['csrf'];return c
 def post(self,c,path,body):return c.post('/api/'+path,json=body,headers={'X-CSRF-Token':c.csrf})
 def photo_data(self,color='red'):
  return test_photo_data(color)
 def event(self,kind='borrow',items=None,token=None,**extra):
  body={'mode':'test','kind':kind,'items':items or {'드라이버':1},'token':token or str(uuid.uuid4()),**extra}
  if kind=='borrow':
   body.setdefault('rent_start','2026-11-09');body.setdefault('rent_due','2026-11-16');body.setdefault('rent_due_hour',18);body.setdefault('plant','제강')
  else: body.setdefault('photo_data',self.photo_data())
  return body

 def stock(self,total=3,version=0,tool='드라이버'):return {'mode':'test','tool':tool,'total':total,'version':version,'reason':'재고 정정','token':str(uuid.uuid4())}
 def test_login_permissions(self):
  for name in ['강라온','박회승','이수민','최인승']:self.login(name)
  self.assertEqual(self.app.test_client().get('/api/state').status_code,401)
  self.assertEqual(self.post(self.worker,'stock',self.stock()).status_code,403)
  self.assertEqual(self.worker.post('/api/events',json=self.event()).status_code,403)
  self.assertEqual(self.post(self.admin,'reservations',{'mode':'test','items':{'드라이버':1},'rent_start':'2026-11-09','rent_due':'2026-11-10','plant':'제강','token':str(uuid.uuid4())}).status_code,403)
  with sqlite3.connect(self.path) as c:self.assertTrue(all(r[0]!='1234' for r in c.execute('select password from users')))
 def test_lifecycle_and_persistence(self):
  self.assertEqual(self.post(self.admin,'stock',self.stock()).status_code,200)
  self.post(self.admin,'stock',self.stock(tool='몽키 스패너'))
  body=self.event(items={'드라이버':2,'몽키 스패너':1});r=self.post(self.worker,'events',body);self.assertEqual(r.status_code,201)
  self.assertEqual(self.post(self.worker,'events',body).json['id'],r.json['id'])
  self.assertEqual(self.post(self.worker,'events',self.event(items={'드라이버':2})).status_code,400)
  self.assertEqual(self.post(self.worker,'events',self.event('return',{'드라이버':3})).status_code,400)
  self.assertEqual(self.post(self.admin,'stock',self.stock(1,1)).status_code,400)
  self.assertEqual(self.post(self.worker,'events',self.event('return')).status_code,201)
  other=create_app(self.path);c=other.test_client();c.post('/api/login',json={'name':'관리자','password':'1234'},headers={'X-STBM-Request':'1'})
  data=c.get('/api/state?mode=test').json;s=data['stock'][0];self.assertEqual((s['total'],s['borrowed'],s['available']),(3,1,2));self.assertEqual(data['events'][0]['name'],'김상협')
  self.assertEqual(c.get('/api/state?mode=demo').json['events'],[])
  self.assertEqual(self.login('강라온').get('/api/state').json['events'],[])
 def test_invalid_duplicate_and_stale(self):
  b=self.stock();self.assertEqual(self.post(self.admin,'stock',b).status_code,200);self.assertTrue(self.post(self.admin,'stock',b).json['duplicate'])
  self.assertEqual(self.post(self.admin,'stock',self.stock(4,0)).status_code,409)
  for value in [-1,1.5,True,'2',100001]:
   b=self.stock(value,1);self.assertEqual(self.post(self.admin,'stock',b).status_code,400)
  b=self.event();self.post(self.worker,'events',b);b['items']={'ドライバー':2};self.assertEqual(self.post(self.worker,'events',b).status_code,400)
 def test_atomic_and_save_failure(self):
  self.post(self.admin,'stock',self.stock())
  self.assertEqual(self.post(self.worker,'events',self.event(items={'드라이버':1,'몽키 스패너':1})).status_code,400)
  with sqlite3.connect(self.path) as c:c.execute("CREATE TRIGGER fail_line BEFORE INSERT ON lines BEGIN SELECT RAISE(ABORT,'test storage failure'); END")
  self.assertEqual(self.post(self.worker,'events',self.event()).status_code,503)
  with sqlite3.connect(self.path) as c:self.assertEqual(c.execute('SELECT count(*) FROM events').fetchone()[0],0)

 def test_event_photo_storage(self):
  from PIL import Image
  self.post(self.admin,'stock',self.stock(total=2))
  r=self.post(self.worker,'events',self.event())
  self.assertEqual(r.status_code,201)
  buf=io.BytesIO();Image.new('RGB',(80,60),'red').save(buf,'JPEG')
  up=self.worker.post('/api/events/%s/photo'%r.json['id'],data={'image':(io.BytesIO(buf.getvalue()),'c.jpg')},headers={'X-CSRF-Token':self.worker.csrf},content_type='multipart/form-data')
  self.assertEqual(up.status_code,200)
  photo=self.worker.get('/api/events/%s/photo'%r.json['id'],headers={'X-CSRF-Token':self.worker.csrf})
  self.assertEqual(photo.status_code,200);self.assertEqual(photo.mimetype,'image/jpeg')
  self.assertTrue(self.worker.get('/api/state').json['groups'][0]['has_photo'])
  other=self.login('강라온')
  self.assertEqual(other.get('/api/events/%s/photo'%r.json['id'],headers={'X-CSRF-Token':other.csrf}).status_code,404)

 def test_return_requires_photo(self):
  self.post(self.admin,'stock',self.stock(total=2))
  self.assertEqual(self.post(self.worker,'events',self.event()).status_code,201)
  body=self.event('return');body.pop('photo_data')
  denied=self.post(self.worker,'events',body)
  self.assertEqual(denied.status_code,400);self.assertIn('사진',denied.json['error'])
  ok=self.post(self.worker,'events',self.event('return'))
  self.assertEqual(ok.status_code,201);self.assertTrue(ok.json['has_photo'])
  self.assertTrue(self.worker.get('/api/state?mode=test').json['groups'][0]['has_photo'])

 def test_concurrent_last_item(self):
  self.post(self.admin,'stock',self.stock(1))
  a=self.login('강라온');b=self.login('박회승')
  with ThreadPoolExecutor(2) as pool:statuses=list(pool.map(lambda c:self.post(c,'events',self.event()).status_code,[a,b]))
  self.assertEqual(sorted(statuses),[201,400]);self.assertEqual(self.admin.get('/api/state').json['stock'][0]['available'],0)




 def test_plant_required_on_borrow(self):
  self.post(self.admin,'stock',self.stock(total=2))
  body=self.event();body.pop('plant')
  self.assertEqual(self.post(self.worker,'events',body).status_code,400)
  ok=self.post(self.worker,'events',self.event(plant='냉연',rent_start='2026-11-10',rent_due='2026-11-20'))
  self.assertEqual(ok.status_code,201);self.assertEqual(ok.json['plant'],'냉연')
  self.assertEqual(ok.json['rent_start'],'2026-11-10');self.assertEqual(ok.json['rent_due'],'2026-11-20')
  st=self.admin.get('/api/state?mode=test').json
  self.assertIn('냉연',st['plants'])
  self.assertTrue(any(h['plant']=='냉연' for h in st['plant_holders']))
  g=next(x for x in st['groups'] if x['id']==ok.json['id'])
  self.assertEqual((g['rent_start'],g['rent_due'],g['rent_due_hour'],g['plant']),('2026-11-10','2026-11-20',18,'냉연'))
  self.assertTrue(any(l['rent_due']=='2026-11-20' and l['rent_due_hour']==18 and l['name']=='김상협' for l in st['active_loans']))

 def test_due_hour_validation_and_boundaries(self):
  self.post(self.admin,'stock',self.stock(total=3))
  for hour in (1,24):
   result=self.post(self.worker,'events',self.event(items={'드라이버':1},rent_due_hour=hour))
   self.assertEqual(result.status_code,201);self.assertEqual(result.json['rent_due_hour'],hour)
  for hour in (0,25,'18'):
   self.assertEqual(self.post(self.worker,'events',self.event(rent_due_hour=hour)).status_code,400)

 def test_damage_report_and_stock_removal(self):
  self.post(self.admin,'stock',self.stock(total=5))
  self.assertEqual(self.post(self.worker,'events',self.event(items={'드라이버':2})).status_code,201)
  r=self.post(self.worker,'events',self.event('return',{'드라이버':2},damage={'드라이버':1},issues={'드라이버':'파손'},damage_note='손잡이 균열'))
  self.assertEqual(r.status_code,201);self.assertEqual(r.json['damage'],{'드라이버':1});self.assertEqual(r.json['issues'],{'드라이버':'파손'})
  st=self.admin.get('/api/state?mode=test').json
  self.assertEqual(st['stock'][0]['damaged'],1);self.assertEqual(st['stock'][0]['available'],4)
  self.assertIn('report',st);self.assertEqual(st['report']['damaged_qty'],1)
  did=next(d['id'] for d in st['damages'] if d['status']=='pending')
  self.assertEqual(self.post(self.admin,f'damages/{did}/process',{}).status_code,200)
  st=self.admin.get('/api/state?mode=test').json
  self.assertEqual(st['stock'][0]['total'],4);self.assertEqual(st['stock'][0]['damaged'],0)
  self.assertEqual(st['stock'][0]['available'],4)
  self.assertTrue(any(a['reason']=='파손' for a in st['adjustments']))

 def test_repair_needed_and_photo_compare(self):
  from PIL import Image
  self.post(self.admin,'stock',self.stock(total=4))
  b=self.post(self.worker,'events',self.event(items={'드라이버':1}))
  self.assertEqual(b.status_code,201)
  buf=io.BytesIO();Image.new('RGB',(60,40),'blue').save(buf,'JPEG')
  up=self.worker.post('/api/events/%s/photo'%b.json['id'],data={'image':(io.BytesIO(buf.getvalue()),'b.jpg')},headers={'X-CSRF-Token':self.worker.csrf},content_type='multipart/form-data')
  self.assertEqual(up.status_code,200)
  st=self.worker.get('/api/state?mode=test').json
  self.assertTrue(any(p['id']==b.json['id'] for p in st['borrow_photos']))
  r=self.post(self.worker,'events',self.event('return',{'드라이버':1},damage={'드라이버':1},issues={'드라이버':'수리 필요'},damage_note='나사 헐거움'))
  self.assertEqual(r.status_code,201);self.assertEqual(r.json['compare_event_id'],b.json['id']);self.assertEqual(r.json['issues']['드라이버'],'수리 필요')
  st=self.admin.get('/api/state?mode=test').json
  did=next(d['id'] for d in st['damages'] if d['status']=='pending' and d['issue']=='수리 필요')
  self.assertEqual(self.post(self.admin,f'damages/{did}/repair',{}).status_code,200)
  st=self.admin.get('/api/state?mode=test').json
  self.assertEqual(st['stock'][0]['total'],4);self.assertEqual(st['stock'][0]['damaged'],0);self.assertEqual(st['stock'][0]['available'],4)
  g=next(x for x in st['groups'] if x['id']==r.json['id'])
  self.assertEqual(g['compare_event_id'],b.json['id']);self.assertTrue(g['has_compare_photo'])


 def test_reservation_approve_fulfill_and_overdue(self):
  from datetime import datetime,timedelta
  from zoneinfo import ZoneInfo
  day=datetime.now(ZoneInfo('Asia/Seoul')).date()
  self.post(self.admin,'stock',self.stock(total=5))
  # reserve 2 drivers
  r=self.post(self.worker,'reservations',{'mode':'test','items':{'드라이버':2},'rent_start':str(day),'rent_due':str(day+timedelta(days=3)),'rent_due_hour':18,'plant':'열연','token':str(uuid.uuid4())})
  self.assertEqual(r.status_code,201);self.assertEqual(r.json['status'],'pending');rid=r.json['id']
  self.assertEqual(self.post(self.worker,f'reservations/{rid}/approve',{}).status_code,403)
  st=self.admin.get('/api/state?mode=test').json
  self.assertEqual(st['stock'][0]['reserved'],2);self.assertEqual(st['stock'][0]['available'],3)
  self.assertEqual(self.post(self.admin,f'reservations/{rid}/approve',{}).status_code,200)
  other=self.login('강라온')
  denied=self.post(other,'reservations',{'mode':'test','items':{'드라이버':1},'rent_start':str(day),'rent_due':str(day+timedelta(days=2)),'plant':'제선','token':str(uuid.uuid4())})
  self.assertEqual(denied.status_code,201)
  rejected=self.post(self.admin,f"reservations/{denied.json['id']}/reject",{})
  self.assertEqual(rejected.status_code,200);self.assertEqual(rejected.json['status'],'rejected')
  # fulfill via borrow linked to reservation
  body=self.event(items={'드라이버':2},rent_start=str(day),rent_due=str(day+timedelta(days=3)),reservation_id=rid,plant='열연')
  self.assertEqual(self.post(self.worker,'events',body).status_code,201)
  st=self.worker.get('/api/state?mode=test').json
  self.assertEqual(st['stock'][0]['reserved'],0);self.assertEqual(st['stock'][0]['borrowed'],2)
  self.assertEqual(st['reservations'][0]['status'],'active')
  # overdue loan: due was 2 days ago → alert after +1 day
  past=self.event(items={'드라이버':1},rent_start=str(day-timedelta(days=5)),rent_due=str(day-timedelta(days=2)))
  self.assertEqual(self.post(self.worker,'events',past).status_code,201)
  overdue=self.worker.get('/api/state?mode=test').json['overdue']
  self.assertTrue(any(o['days_overdue']>=1 for o in overdue))
  # return clears overdue for returned qty path
  self.assertEqual(self.post(self.worker,'events',self.event('return',{'드라이버':3})).status_code,201)
  self.assertEqual(self.worker.get('/api/state?mode=test').json['overdue'],[])

if __name__=='__main__':unittest.main()

class IntegratedTest(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.app=create_app(Path(self.tmp.name)/'db.sqlite3');self.app.testing=True;self.c=self.app.test_client()
  self.me=self.c.post('/api/login',json={'name':'관리자','password':'1234'},headers={'X-STBM-Request':'1'}).json
 def tearDown(self):self.tmp.cleanup()
 def test_grouped_kpi_and_qr(self):
  h={'X-CSRF-Token':self.me['csrf']}
  for t in ['드라이버','몽키 스패너']:
   self.assertEqual(self.c.post('/api/stock',json={'tool':t,'total':5,'version':0,'reason':'신규 구매 및 추가','token':str(uuid.uuid4())},headers=h).status_code,200)
  for kind in ['borrow','return']:
   body={'kind':kind,'items':{'드라이버':2,'몽키 스패너':1},'token':str(uuid.uuid4())}
   if kind=='borrow':body.update(rent_start='2026-11-09',rent_due='2026-11-16',plant='제선')
   else:body['photo_data']=test_photo_data()
   self.assertEqual(self.c.post('/api/events',json=body,headers=h).status_code,201)
  d=self.c.get('/api/state').json;self.assertEqual(d['return_count'],1);self.assertEqual(len(d['groups']),2);self.assertEqual(len(d['groups'][0]['items']),2)
  self.assertEqual(d['groups'][0]['status'],'완료');self.assertEqual(self.c.get('/api/qr').mimetype,'image/svg+xml')
 def test_camera_unavailable_and_protected_routes(self):
  self.assertEqual(self.app.test_client().get('/admin').status_code,302)
  c=self.app.test_client();me=c.post('/api/login',json={'name':'김상협','password':'1234'},headers={'X-STBM-Request':'1'}).json
  self.assertEqual(c.get('/admin').status_code,403);self.assertEqual(c.get('/api/qr').status_code,403)
  self.assertFalse(c.get('/api/config').json['ai_ready'])
  import io
  r=c.post('/api/recognize',data={'image':(io.BytesIO(b'test'),'test.jpg')},headers={'X-CSRF-Token':me['csrf']})
  self.assertEqual(r.status_code,503);self.assertNotIn('items',r.json)
