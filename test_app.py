import unittest, tempfile, sqlite3, uuid
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from app import create_app

class AppTest(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'test.sqlite3';self.app=create_app(self.path);self.app.testing=True
  self.admin=self.login('관리자');self.worker=self.login('김상협')
 def tearDown(self):self.tmp.cleanup()
 def login(self,name):
  c=self.app.test_client();r=c.post('/api/login',json={'name':name,'password':'1234'},headers={'X-STBM-Request':'1'});self.assertEqual(r.status_code,200);c.csrf=r.json['csrf'];return c
 def post(self,c,path,body):return c.post('/api/'+path,json=body,headers={'X-CSRF-Token':c.csrf})
 def event(self,kind='borrow',items=None,token=None):return {'mode':'test','kind':kind,'items':items or {'드라이버':1},'token':token or str(uuid.uuid4())}
 def stock(self,total=3,version=0,tool='드라이버'):return {'mode':'test','tool':tool,'total':total,'version':version,'reason':'재고 정정','token':str(uuid.uuid4())}
 def test_login_permissions(self):
  for name in ['강라온','박회승','이수민','최인승']:self.login(name)
  self.assertEqual(self.app.test_client().get('/api/state').status_code,401)
  self.assertEqual(self.post(self.worker,'stock',self.stock()).status_code,403)
  self.assertEqual(self.worker.post('/api/events',json=self.event()).status_code,403)
  with sqlite3.connect(self.path) as c:self.assertTrue(all(r[0]!='1234' for r in c.execute('select password from users')))
 def test_lifecycle_and_persistence(self):
  self.assertEqual(self.post(self.admin,'stock',self.stock()).status_code,200)
  self.post(self.admin,'stock',self.stock(tool='렌치'))
  body=self.event(items={'드라이버':2,'렌치':1});r=self.post(self.worker,'events',body);self.assertEqual(r.status_code,201)
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
  self.assertEqual(self.post(self.worker,'events',self.event(items={'드라이버':1,'렌치':1})).status_code,400)
  with sqlite3.connect(self.path) as c:c.execute("CREATE TRIGGER fail_line BEFORE INSERT ON lines BEGIN SELECT RAISE(ABORT,'test storage failure'); END")
  self.assertEqual(self.post(self.worker,'events',self.event()).status_code,503)
  with sqlite3.connect(self.path) as c:self.assertEqual(c.execute('SELECT count(*) FROM events').fetchone()[0],0)
 def test_concurrent_last_item(self):
  self.post(self.admin,'stock',self.stock(1))
  a=self.login('강라온');b=self.login('박회승')
  with ThreadPoolExecutor(2) as pool:statuses=list(pool.map(lambda c:self.post(c,'events',self.event()).status_code,[a,b]))
  self.assertEqual(sorted(statuses),[201,400]);self.assertEqual(self.admin.get('/api/state').json['stock'][0]['available'],0)
if __name__=='__main__':unittest.main()

class IntegratedTest(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.app=create_app(Path(self.tmp.name)/'db.sqlite3');self.app.testing=True;self.c=self.app.test_client()
  self.me=self.c.post('/api/login',json={'name':'관리자','password':'1234'},headers={'X-STBM-Request':'1'}).json
 def tearDown(self):self.tmp.cleanup()
 def test_grouped_kpi_and_qr(self):
  h={'X-CSRF-Token':self.me['csrf']}
  for t in ['드라이버','렌치']:
   self.assertEqual(self.c.post('/api/stock',json={'tool':t,'total':5,'version':0,'reason':'신규 구매 및 추가','token':str(uuid.uuid4())},headers=h).status_code,200)
  for kind in ['borrow','return']:
   self.assertEqual(self.c.post('/api/events',json={'kind':kind,'items':{'드라이버':2,'렌치':1},'token':str(uuid.uuid4())},headers=h).status_code,201)
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
