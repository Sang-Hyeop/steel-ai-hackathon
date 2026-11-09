## 최종 모델 — tools_yolo11n_v4.pt

PC 실행(`SmartToolBox_실행.py`)과 QR/휴대폰 실행(`SmartToolBox_휴대폰_실행.py`) 모두 `model_config.py`를 통해 이 가중치를 고정 사용합니다.

- 추론: imgsz **640**, conf **0.35**
- 클래스: screwdriver / wrench / pliers / hammer
- 선택 근거: v2·v3·v5 대비 공개 크롭·진단 실사진에서 가장 균형이 좋음. v5는 실사진 회귀로 제외.
- 설정 파일: `models/FINAL.json`, `model_config.py`

인식 결과는 자동 확정하지 않습니다. 사용자가 확인·수정 후 저장합니다.

---

### 보관 가중치

- `tools_yolo11n_v2.pt`: 이전 로컬 연결 후보. 최종 아님.
- `candidates/tools_yolo11n_v5.pt`: 장면 파인튜닝 후보. 실사진 회귀로 미채택.
- `yolo11n.pt`: Ultralytics 사전학습 원본.

상세 학습 기록은 `tools/AI_학습_안내.md`를 참고하세요.
