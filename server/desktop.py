"""데스크톱 앱(Electron)이 띄우는 서버 진입점.

    pythonw -m server.desktop        (Windows: 콘솔 없는 pythonw로 띄워 창이 뜨지 않는다)

포트, 데이터 폴더는 앱이 환경 변수(JUNGLE_PORT, JUNGLE_VODS, JUNGLE_KB, JUNGLE_DB)로 넘긴다.
"""

from __future__ import annotations

import os
import sys


def main() -> None:
    # Windows 기본 인코딩(cp1252 등)으로는 한글 JSON을 못 읽는다. UTF-8 모드가 아니면 UTF-8 모드로 다시 실행
    if not sys.flags.utf8_mode:
        os.environ["PYTHONUTF8"] = "1"
        os.execv(sys.executable, [sys.executable, "-X", "utf8", "-m", "server.desktop", *sys.argv[1:]])
    # pythonw는 표준 출력이 없을 수 있다. 앱이 파이프를 안 줬으면 로그 파일로
    if sys.stdout is None or sys.stderr is None:
        log = open(os.path.join(os.environ.get("JUNGLE_VODS", "."), "server.log"), "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stdout or log
        sys.stderr = sys.stderr or log
    os.environ.setdefault("JUNGLE_DESKTOP", "1")
    import uvicorn

    port = int(os.environ.get("JUNGLE_PORT", "8790"))
    uvicorn.run("server.app:app", host=os.environ.get("JUNGLE_HOST", "127.0.0.1"), port=port, log_level="warning")


if __name__ == "__main__":
    main()
