"""Smart Tool Box 실행: 기본은 고정 주소, --local은 개발 서버."""
import os
import sys
import socket
import threading
import webbrowser
from pathlib import Path

ROOT=Path(__file__).resolve().parent
SAFETY=Path('/opt/anaconda3/envs/safety/bin/python')
PUBLIC_URL='https://sanghyeopkim.pythonanywhere.com/'

def main():
    if '--local' not in sys.argv:
        print(f'\nSmart Tool Box 고정 주소: {PUBLIC_URL}\n',flush=True)
        if not webbrowser.open(PUBLIC_URL):
            print('브라우저에서 위 주소를 직접 열어주세요.',flush=True)
        return
    if SAFETY.is_file() and Path(sys.executable).resolve()!=SAFETY.resolve():
        os.execv(str(SAFETY),[str(SAFETY),str(Path(__file__).resolve()),*sys.argv[1:]])
    try:
        from app import create_app
        from werkzeug.serving import make_server
    except ImportError as e:
        print('필요한 패키지가 없습니다. safety 환경에서 다음 명령을 실행하세요:')
        print(f'python -m pip install -r "{ROOT / "requirements.txt"}"')
        raise SystemExit(1) from e
    from model_config import apply_model_env
    apply_model_env(required=True)
    app=create_app()
    port=int(os.environ.get('PORT','8001'))
    # Bind before opening the browser. A busy port must never open an unrelated app.
    for candidate in range(port,port+20):
        with socket.socket() as probe:
            try: probe.bind(('127.0.0.1',candidate))
            except OSError: continue
        try:
            server=make_server('127.0.0.1',candidate,app,threaded=True)
            break
        except (OSError,SystemExit): continue
    else: raise SystemExit('사용 가능한 포트가 없습니다. PORT 환경변수를 변경하세요.')
    url=f'http://127.0.0.1:{candidate}/'
    print(f'\nSmart Tool Box 실행 중: {url}\n종료: Control+C\n',flush=True)
    # A QR defaults to the actual listening address, including fallback ports.
    os.environ.setdefault('STBM_PUBLIC_URL',PUBLIC_URL)
    thread=threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    if '--no-browser' not in sys.argv:
        if not webbrowser.open(url): print('브라우저에서 위 주소를 직접 열어주세요.',flush=True)
    try: thread.join()
    except KeyboardInterrupt: print('\n서버를 종료합니다.')
    finally: server.shutdown();server.server_close()

if __name__=='__main__': main()
