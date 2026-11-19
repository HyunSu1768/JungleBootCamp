# 녹화 에이전트

게임하는 PC에서 켜 두면 롤 게임이 시작될 때 자동으로 화면을 녹화하고, 판이 끝나면 서버로 보내요.
서버는 받은 녹화를 정리하고 정글 판이면 바로 분석해요. 결과는 웹의 '내 게임'에 나와요.

## 어떻게 동작하나
- 롤 클라이언트는 게임 중에만 `https://127.0.0.1:2999/liveclientdata/`(Live Client Data API, Riot 공식)를 열어요. 2초마다 확인해서 소환사의 협곡 게임이 시작되면 녹화를 시작해요. 연습 모드, 칼바람, 관전, 리플레이는 녹화하지 않아요.
- 녹화하는 동안 같은 API로 인게임 시계, 킬, 오브젝트 이벤트, 10초마다 10명의 레벨, KDA, CS, 아이템을 `live.json`에 남겨요. 분석이 화면만 보고 추측하지 않고 정확한 기록을 쓰게 하려는 거예요.
- `GameEnd` 이벤트가 오고 4초 뒤(승패 화면까지) 녹화를 끝내요. 게임이 비정상으로 꺼지면 API가 12초 동안 응답하지 않을 때 끝내요.
- 게임 메모리를 읽거나 게임 파일을 건드리지 않아요.

## Windows 설치
PowerShell에서:

```powershell
winget install -e Python.Python.3.12 Gyan.FFmpeg     # 처음 한 번 (ffmpeg 6 이상 필요)
curl.exe -o recorder.py http://<서버 주소>:8790/api/agent/recorder.py
python recorder.py --server http://<서버 주소>:8790 --token <연결 토큰>
```

연결 토큰은 웹 '내 게임 > 연결하기'에서 받아요. 서버를 다른 PC에서 돌리면 서버 PC에서 `HOST=0.0.0.0 ./run.sh`로 켜야 같은 네트워크에서 접속돼요.

- 녹화: Desktop Duplication(`ddagrab`)으로 화면을 GPU에서 가져오고 그래픽카드 인코더(NVIDIA NVENC → AMD AMF → Intel QSV 순)로 1080p 30fps, 6Mbps로 저장해요. 35분 판 하나가 약 1.5GB예요. 그래픽카드 인코더가 없으면 CPU(libx264 ultrafast)를 쓰는데 게임 프레임이 떨어질 수 있어요.
- 롤은 **테두리 없음** 창 모드를 권장해요. 모니터가 여러 개면 `--screen 1`처럼 롤이 뜨는 모니터 번호를 넣어요.
- 소리는 기본으로 녹음하지 않아요. 디스코드나 게임 소리를 같이 남기려면 `--audio "스테레오 믹스(Realtek(R) Audio)"`처럼 dshow 오디오 장치 이름을 넣어요(`ffmpeg -list_devices true -f dshow -i dummy`로 확인).
- 서버로 다 보낸 녹화는 PC에 최근 10개만 남겨요(`--keep`).
- 서버가 꺼져 있어도 녹화는 계속하고, 다음에 서버가 켜지면 밀린 녹화를 이어서 올려요. 업로드는 16MB 조각으로 나눠 보내고, 끊기면 받은 데까지 이어서 보내요.

## macOS
`python3 recorder.py --server http://127.0.0.1:8790 --token <토큰> --local`
처음 실행할 때 터미널에 '화면 기록' 권한을 줘야 해요(시스템 설정 > 개인정보 보호 및 보안 > 화면 및 시스템 오디오 기록). `--local`은 서버와 같은 PC일 때 파일을 올리지 않고 경로만 넘겨요.

## 실서비스로 가려면
- 지금은 Python 스크립트예요. 사용자 배포는 Tauri나 Electron 트레이 앱으로 감싸고 ffmpeg를 같이 넣어요(로그인하면 토큰을 자동으로 받게).
- Live Client Data API를 쓰는 앱을 공개 배포하려면 Riot 개발자 포털에 제품 등록이 필요해요.
- 녹화 원본 업로드는 서버 대신 객체 저장소(S3 등)로 바로 보내는 서명 URL 방식이 좋아요. `/api/agent/uploads`가 그 자리를 대신하고 있어요.
