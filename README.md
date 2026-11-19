# 정글러훈련소 (JungleBootCamp)

롤 정글러의 티어를 올리는 판단 훈련 앱이에요.

- **예측 훈련**: 프로 영상과 내 게임의 판단 직전 장면에서 영상이 멈추고, 15초 안에 고르면 정답과 이유를 보여 줘요. 틀린 문제는 간격을 두고 다시 나와요.
- **내 게임 자동 녹화**: 앱을 켜 두면 롤 게임이 시작될 때 알아서 녹화하고, 끝나면 정글 판을 Claude가 분석해요.
- **프로 영상 분석**: 숲(SOOP) 다시보기 링크를 넣으면 판을 찾아 플랜, 턴, 운영, 교전으로 분석해요.

## 설치 (Windows)
[Releases](https://github.com/HyunSu1768/JungleBootCamp/releases/latest)에서 `JungleBootCamp-Setup-*.exe`를 받아 실행해요.
처음 켜면 분석 도구(파이썬, 받아쓰기 모델)를 설치하고, Claude 로그인 → 티어 → 녹화 설정 순서로 안내해요.
새 버전은 자동으로 받아서 앱을 다시 켤 때 설치돼요.

> 아직 코드 서명을 하지 않아서 처음 설치할 때 'Windows의 PC 보호' 창이 뜰 수 있어요. '추가 정보 → 실행'을 눌러 주세요.

필요한 것: Windows 10/11 64비트, Claude Pro 또는 Max 구독(분석에 씀).

## 구조
- `server/`: FastAPI 서버 (작업 큐, 훈련, 내 게임, 설정). `server/platform_util.py`가 Windows에서 하위 프로세스 콘솔 창을 숨긴다.
- `tools/`: 영상 받기, 프레임, 받아쓰기, 교전 후보 스크립트
- `agent/recorder.py`: 롤 Live Client Data API로 게임을 감지해 자동 녹화
- `web/`: React 화면
- `desktop/`: Electron 앱 (서버를 띄우고, 트레이 상주, 자동 업데이트)
- `.claude/skills/jungle-vod/`: 분석 절차 (Claude가 읽음), 형식은 `SCHEMA.md`

## 개발
- 맥: `./run.sh` → http://127.0.0.1:8790
- 데스크톱 앱(개발): `cd desktop && npm install && JUNGLE_DEV_PYTHON=$(pwd)/../.venv/bin/python npx electron .`

## 릴리스
`main`에 푸시하면 GitHub Actions(`.github/workflows/release.yml`)가 Windows에서 스모크 테스트 → 설치 파일 빌드 → 릴리스(`v0.1.<실행 번호>`)까지 해요. 앞 두 자리는 `desktop/package.json`의 version으로 정해요.
