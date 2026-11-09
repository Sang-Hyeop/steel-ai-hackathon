# PythonAnywhere 배포 안내 (고정 QR용)

휴대폰의 `sanghyeopkim.pythonanywhere.com` 과 컴퓨터의 `127.0.0.1:8001` 은 **서로 다른 서버·다른 DB**입니다.  
이름 변경(몽키 스패너)·출납 기록이 양쪽에 같이 보이려면 **PythonAnywhere에도 최신 코드를 올려야** 합니다.

## 1. 로컬에서 최신 코드 푸시

```sh
cd "/Users/sanghyeopkim/Desktop/제철소 AI 해커톤"
git status
git push
```

GitHub: https://github.com/Sang-Hyeop/steel-ai-hackathon

## 2. PythonAnywhere에서 코드 받기

1. [PythonAnywhere](https://www.pythonanywhere.com/) 로그인
2. **Consoles** → Bash
3. 프로젝트가 이미 clone 되어 있다면:

```sh
cd ~/steel-ai-hackathon   # 실제 폴더명이 다르면 그 경로로
git pull origin main
# 또는 작업 브랜치라면:
# git pull origin feature/stbm-final-model-and-app
```

처음이면:

```sh
cd ~
git clone https://github.com/Sang-Hyeop/steel-ai-hackathon.git
cd steel-ai-hackathon
```

## 3. 패키지 설치 (웹앱용 virtualenv)

Web 탭에 연결된 virtualenv에서:

```sh
# 예시 경로 — Web 탭 Virtualenv 경로와 맞출 것
source ~/.virtualenvs/stbm/bin/activate
pip install -r requirements.txt
```

`ultralytics` / torch 는 Free 플랜에서 무겁거나 실패할 수 있습니다.  
그 경우에도 **대시보드·출납·이름 변경**은 동작하고, AI 인식만 수동 입력으로 대체됩니다.

최종 모델 파일이 서버에 필요하면 로컬의 `models/tools_yolo11n_v4.pt` 를  
Files 탭으로 `~/steel-ai-hackathon/models/` 에 업로드하세요. (Git에 포함되어 있으면 pull 만으로 충분)

## 4. WSGI 설정

**Web** → WSGI configuration file 을 열고, 대략 아래로 맞춥니다.  
경로·유저명은 본인 계정에 맞게 수정하세요.

```python
import sys
import os

project = "/home/sanghyeopkim/steel-ai-hackathon"
if project not in sys.path:
    sys.path.insert(0, project)

os.environ["STBM_PUBLIC_URL"] = "https://sanghyeopkim.pythonanywhere.com/"
os.environ["STBM_HTTPS"] = "1"
# AI 모델을 서버에 둔 경우:
# os.environ["STBM_MODEL_PATH"] = "/home/sanghyeopkim/steel-ai-hackathon/models/tools_yolo11n_v4.pt"
# os.environ["STBM_MODEL_IMGSZ"] = "640"
# os.environ["STBM_MODEL_CONF"] = "0.35"

from app import create_app
application = create_app()
```

## 5. Static 파일 매핑

**Web** → Static files:

| URL | Directory |
|-----|-----------|
| `/static/` | `/home/sanghyeopkim/steel-ai-hackathon/static/` |

## 6. Reload

Web 탭 상단 **绿色 Reload** 버튼 클릭.

앱 기동 시 `create_app()` 이 DB의 옛 이름 `렌치` 를 `몽키 스패너` 로 자동 마이그레이션합니다.

## 7. 확인

1. 폰에서 https://sanghyeopkim.pythonanywhere.com/ 새로고침 (필요하면 캐시 삭제)
2. 공구별 재고에 **몽키 스패너** 표시 확인
3. 컴퓨터에서도 **같은 주소**로 관리자 로그인하면 휴대폰과 **같은 사용자·같은 기록**이 보입니다

## 자주 하는 실수

| 증상 | 원인 |
|------|------|
| 폰은 여러 사용자, PC는 김상협만 | PC가 localhost, 폰이 PythonAnywhere |
| PC만 몽키 스패너, 폰은 렌치 | PA에 코드 미배포 |
| QR이 `127.0.0.1` | 로컬 실행 화면의 QR. 고정 QR은 PA 주소를 써야 함 |

고정 QR / 시연용 관리자 화면은 앞으로는  
**항상 `https://sanghyeopkim.pythonanywhere.com/`** 기준으로 맞추는 것을 권장합니다.
