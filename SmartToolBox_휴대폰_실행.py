"""휴대폰 HTTPS 테스트 실행. 종료하면 임시 주소도 닫힙니다."""
import os,sys,threading,subprocess,re,time,queue,webbrowser
from pathlib import Path
ROOT=Path(__file__).resolve().parent
SAFETY=Path('/opt/anaconda3/envs/safety/bin/python')
def main():
 if SAFETY.exists() and Path(sys.executable).resolve()!=SAFETY.resolve():os.execv(str(SAFETY),[str(SAFETY),str(Path(__file__).resolve()),*sys.argv[1:]])
 from werkzeug.serving import make_server
 from app import create_app
 import qrcode
 binary=ROOT/'tools'/'cloudflared'
 if not binary.exists():raise SystemExit('tools/cloudflared가 없습니다. HTTPS 터널 도구 설치가 필요합니다.')
 from model_config import apply_model_env
 apply_model_env(required=True)
 os.environ['STBM_HTTPS']='1'
 app=create_app();server=make_server('127.0.0.1',0,app,threaded=True)
 local=f'http://127.0.0.1:{server.server_port}'
 threading.Thread(target=server.serve_forever,daemon=True).start()
 proc=None
 try:
  proc=subprocess.Popen([str(binary),'tunnel','--url',local,'--protocol','http2','--no-autoupdate'],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
  lines=queue.Queue()
  def read():
   for line in proc.stdout:lines.put(line)
  threading.Thread(target=read,daemon=True).start()
  deadline=time.monotonic()+90;url=None
  while time.monotonic()<deadline:
   try:line=lines.get(timeout=1)
   except queue.Empty:
    if proc.poll() is not None:raise RuntimeError('HTTPS 터널이 종료되었습니다.')
    continue
   match=re.search(r'https://[a-z0-9-]+\.trycloudflare\.com',line)
   if match:url=match.group();break
  if not url:raise RuntimeError('HTTPS 주소 생성 시간이 초과되었습니다. 인터넷 연결을 확인하세요.')
  os.environ['STBM_PUBLIC_URL']=url
  folder=ROOT/'instance';qrcode.make(url).save(folder/'mobile-qr.png');(folder/'mobile-url.txt').write_text(url)
  print(f'\n휴대폰 접속: {url}\nQR 파일: {folder / "mobile-qr.png"}\n이 창을 유지하세요. 종료: Control+C\n',flush=True)
  if '--no-browser' not in sys.argv:webbrowser.open(url);webbrowser.open((folder/'mobile-qr.png').as_uri())
  while proc.poll() is None:time.sleep(1)
  raise RuntimeError('HTTPS 연결이 종료되었습니다. 실행 파일을 다시 실행하세요.')
 except KeyboardInterrupt:print('\n휴대폰 접속을 종료합니다.')
 finally:
  if proc and proc.poll() is None:
   proc.terminate()
   try:proc.wait(timeout=5)
   except subprocess.TimeoutExpired:proc.kill();proc.wait()
  server.shutdown();server.server_close()
if __name__=='__main__':main()
