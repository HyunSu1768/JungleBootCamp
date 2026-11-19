#!/bin/zsh
# 정글러훈련소 실행: 프론트를 빌드하고 서버를 띄운다
set -e
cd "$(dirname "$0")"
if [ ! -d web/node_modules ]; then (cd web && npm install); fi
(cd web && npm run build)
PORT=${PORT:-8790}
# 게임하는 PC가 따로 있으면(녹화 에이전트) HOST=0.0.0.0 ./run.sh 로 같은 네트워크에 연다
HOST=${HOST:-127.0.0.1}
( sleep 1.5 && open "http://127.0.0.1:$PORT" ) &
exec uv run uvicorn server.app:app --host "$HOST" --port "$PORT"
