# 데이터 형식

웹 화면이 이 JSON 파일들을 그대로 읽는다. 필드 이름, 형식을 지키고, 쓰기 전에 기존 파일을 읽어 덮어쓰지 않게 병합한다.
JSON은 반드시 유효해야 한다(쓰고 나서 `uv run python -m json.tool <파일> > /dev/null`로 확인).
아래 예시의 `// 주석`은 설명용이다. 실제 파일에는 주석을 쓰지 않는다.

공통 규칙
- 시각 문자열: VOD 시각은 `"H:MM:SS"`, 인게임 시각은 `"M:SS"`(30분 넘으면 `"32:10"`).
- `source`: 근거. `"quote"` = 경기 중 스트리머 발언(받아쓰기), `"team"` = 팀원 보이스(스트리머가 아닌 사람의 콜), `"review"` = 경기 뒤 리플레이를 보며 한 발언, `"screen"` = 화면으로 확인, `"guess"` = 추정.
  `review`는 결과를 알고 하는 말이라 그때의 의도와 다를 수 있다. 의도는 `quote`가 있으면 그걸 우선하고, `review`는 "돌아보니 어땠나"로 쓴다.
- 이미지 경로(`frames`, `image`)는 **vods 폴더 기준 상대 경로**. 예: `"123_streamer/game2/frames/1-26-35.jpg"`. 실제로 존재하는 파일만 넣는다.
- `game_ref`: `"<vod 폴더 이름>/<게임 이름>"`. 예: `"123_streamer/game2"`.
- id는 영문 소문자, 숫자, 하이픈 (`gank-decision`, `t3`).
- 개념과 원칙의 `category`는 이 중 하나: `밴픽`, `라인 상성`, `초반 동선`, `턴 운영`, `갱킹`, `카정·맞갱`, `오브젝트`, `교전`, `중후반 운영`, `시야`
- 독자는 플래티넘 이상 정글러다. 기본기 설명은 쓰지 않고, 용어(카정, 맞갱, 프리징, 다이브, 템포, 사이드)는 그대로 쓴다.

## vods/<vod>/games.json (판 찾기 결과)
```json
{
  "games": [
    {
      "n": 1,
      "draft_start": "1:20:30",   // 픽창이 처음 보이는 시각, 못 찾으면 null
      "start": "1:23:00",         // 인게임 HUD가 처음 보이는 시각
      "end": "1:58:30",           // 승리/패배 화면 시각
      "jungle": true,
      "mode": "솔로랭크",          // 솔로랭크, 자유랭크, 칼바람, 내전, 대회 같이보기, 기타
      "champion": "리 신",
      "result": "승",              // "승" | "패" | null
      "note": "한 줄 메모",
      "reviews": [                 // 이 판이 끝난 뒤 리플레이를 보며 피드백한 구간. 없으면 []
        {"from": "1:59:00", "to": "2:08:00", "note": "킬 장면 위주로 돌려 봄"}
      ]
    }
  ],
  "other_reviews": [               // 어느 판인지 연결 못 한 리플레이 (다른 사람 게임, 이 VOD에 없는 판)
    {"from": "7:10:00", "to": "7:18:00", "note": "시청자 게임 리플레이 피드백"}
  ]
}
```
리플레이 화면 구분: 화면 아래 재생 막대(재생, 배속 버튼, 진행 바), 위쪽에 양 팀 골드와 킬이 함께 나오는 관전 점수판, 양 팀 아이템이 다 보이는 아래 패널.
라이브 관전 HUD와 비슷하니, 판이 끝난 직후(승리/패배 화면 다음)에 같은 챔피언 구성이 다시 보이면 그 판의 리플레이로 본다.

## vods/<vod>/<game>/analysis.json (한 판 분석)
한 판을 세 층으로 본다. **플랜**(시작 전에 정해지는 것) → **턴**(플랜을 시간 단위로 어떻게 썼나) → **운영**(게임 전체 흐름). 교전은 따로 뜯어본다.

```json
{
  "version": 2,
  "streamer": "스트리머 이름",
  "champion": "리 신",
  "enemy_jungler": "비에고",
  "result": "승",
  "length": "28:10",
  "context": "솔로랭크",           // 솔로랭크 | 자유랭크 | 내전 | 대회. 내전, 대회는 소통하는 팀 게임이라 솔로랭크와 다를 수 있다
  "own": false,                   // 내 게임 분석(스킬 C)이면 true. streamer는 null
  // 내 게임만: "goal_check": {...}, "next_goal": {...} (스킬 C 참고),
  //   "coach": {headline, fixes[], keeps[], self_check, lessons[]} (판 전체 총평, 스킬 D '총평 담당'. lessons는 앱이 복기 노트(DB)에 쌓는다)
  "summary": ["이 판의 흐름 3~5줄. 플랜 → 턴 → 운영이 어떻게 이어졌는지"],
  "takeaways": ["플래티넘 이상이 가져갈 배움 3개. 일반론이 아니라 이 판의 조건이 붙은 판단"],

  "plan": { ... },
  "turns": { ... },
  "operations": { ... },
  "fights": [ ... ],
  "review": { ... },              // 리플레이 피드백. 없으면 {"available": false}

  "new_concepts": ["gank-decision"],
  "new_rules": ["r-gank-pushed-lane"],
  "new_quizzes": ["q-123-game2-1"]
}
```

### plan (1층: 게임 플랜)
```json
{
  "draft": {
    "available": true,              // 픽창 자료가 없으면 false, 아래 draft 필드 생략
    "side": "블루",
    "bans": {"ally": ["..."], "enemy": ["..."]},
    "picks": {
      "ally":  [{"order": 1, "champion": "오리아나", "role": "미드"}],
      "enemy": [{"order": 1, "champion": "비에고", "role": "정글"}]
    },
    "my_pick": {"champion": "리 신", "order": 2, "reason": "...", "source": "quote", "quote": "원문 또는 null"},
    "frames": []
  },
  "lanes": [
    {
      "lane": "탑",                  // 탑 | 미드 | 바텀
      "ally": "레넥톤",               // 바텀은 "카이사 + 노틸러스"
      "enemy": "가렌",
      "priority": "ally",            // 1~3레벨 라인 주도권: ally | enemy | even
      "spikes": "레넥톤 2~3레벨 킬각, 가렌은 6레벨 이후 올인 위협",
      "gank_setup": "레넥톤 W 스턴으로 호응 좋음",
      "dive": "3레벨 이후 다이브 가능",
      "verdict": "gank",             // gank(갈 라인) | protect(지킬 라인) | ignore(버릴 라인)
      "reason": "왜 그렇게 판단했나",
      "source": "quote",
      "actual": "실제 초반 3분 라인 상태 (화면으로 확인한 CS, 레벨, 라인 위치)",
      "background": ["이 판단을 이해하는 데 필요한 챔피언 지식. 예: 애쉬 W는 부채꼴 둔화라 수풀에서 다가오는 정글을 미리 맞혀 갱 진입이 느려진다"]
    }
  ],
  "junglers": {
    "ally":  {"champion": "리 신",  "early": "2~3캠프 후 교전 강함", "first_path": "레드 → 바텀 마무리", "source": "screen"},
    "enemy": {"champion": "비에고", "early": "풀캠 전 교전 약함",    "first_path": "탑 쪽 시작 예상(추정)", "source": "guess"}
  },
  "win_conditions": {"ally": "...", "enemy": "..."},
  "jungle_plan": "한 줄 정글 플랜. 예: 바텀 2:1 구도라 첫 턴은 바텀, 첫 용 우선, 비에고 첫 귀환 때 탑 쪽 카정",
  "plan_source": "quote",
  "plan_quote": "픽창, 로딩 중 발언 원문 또는 null",
  "loading_frame": "로딩 화면이나 게임 시작 직후 프레임 경로 또는 null"
}
```

### turns (2층: 턴)
한 턴 = 게임 시작이나 귀환/사망 후 부활부터 **다음 귀환이나 사망까지**. 행동(action)은 그 안의 캠프, 갱, 카정, 오브젝트 단위.
```json
{
  "ally": [
    {
      "id": "t1",
      "from": "1:30",               // 인게임
      "to": "3:45",
      "vod_from": "1:24:30",
      "end": "귀환",                 // 귀환 | 사망 | 게임 끝
      "start_state": {
        "level": 1, "gold": 500, "cs": 0,
        "lanes": "탑 우리 쪽으로 밀림, 바텀 상대가 밀어 둠",
        "next_objective": "유충 6:00 / 용 5:00",
        "enemy_jungler": "마지막 확인: 1:30 상대 블루 쪽 (추정)"
      },
      "actions": [
        {"t": "1:30", "kind": "파밍",  "label": "레드",        "where": "우리 레드"},
        {"t": "2:15", "kind": "파밍",  "label": "칼날부리",     "where": "우리 칼날부리"},
        {"t": "3:10", "kind": "갱킹",  "label": "바텀 갱",      "where": "바텀", "result": "서폿 킬, 점멸 뺌",
         "why": "파밍이 아닌 행동은 왜 했는지 한 줄. 예: 상대 서폿 점멸이 2:40에 빠졌고 웨이브가 우리 포탑 앞이라"},
        {"t": "3:40", "kind": "귀환",  "label": "귀환",         "where": "바텀 부쉬"}
      ],
      "intent": "이번 턴을 이렇게 쓴 의도",
      "source": "quote",
      "quote": "원문 또는 null",
      "followed_plan": "yes",       // yes | partial | no
      "deviation": "플랜에서 벗어났다면 이유, 아니면 null",
      "decisions": [                // 이 턴의 판단 포인트 2~4개. 턴 카드의 핵심이다
        {
          "id": "t1-d1",             // <턴 id>-d<번호>. 훈련 문제 id로 쓰니 바꾸지 않는다
          "t": "2:45",
          "category": "갱킹",          // 개념, 원칙과 같은 카테고리 중 하나. 약점 집계에 쓴다
          "question": "블루 먹고 바텀 갈까, 탑 바위게 볼까?",
          "situation": "그때 보이던 것을 문장으로: 라인별 웨이브 위치와 CS, 스펠 상태, 상대 정글 마지막 위치와 시각, 오브젝트 타이머, 내 체력과 스킬",
          "options": [
            {"label": "바텀 갱", "chosen": true,  "best": true,  "why": "고른 이유"},
            {"label": "탑 바위게", "chosen": false, "best": false, "why": "안 고른 이유, 또는 골랐다면 어땠을지"}
          ],
          "verdict": "좋은 선택",        // 좋은 선택 | 아쉬운 선택 | 애매. 실제 선택(chosen)이 best가 아니면 아쉬운 선택
          // best: 이 상황에서 더 나은 선택. 근거는 결과, 리플레이 피드백, kb 원칙. 확실하지 않으면 실제 선택을 best로 두고 verdict는 "애매"
          // 훈련 문제의 정답은 best다. 선택지는 2~3개, 각각 그럴듯해야 한다(정답이 뻔한 문제는 훈련 가치가 없다)
          "why": "스트리머가 이걸 고른 이유. 발언이 있으면 그걸로",
          "source": "quote", "quote": "원문 또는 null",
          "result": "어떻게 됐나",
          "background": ["이 판단을 이해하려면 알아야 할 챔피언, 메커니즘 지식 0~2개. 이 판 챔피언을 안 해 본 플래티넘도 이해하게"],
          "frames": []
        }
      ],
      "gained": ["킬 1", "바텀 주도권"],
      "lost": ["바위게"],
      "exchange": "같은 시간 상대 정글이 한 일과 교환 결과. 모르면 '상대 정글 위치 모름'",
      "verdict": "이득",            // 이득 | 교환 | 손해
      "frames": []
    }
  ],
  "enemy": [
    {
      "id": "e1", "from": "1:30", "to": "3:30",
      "actions": [{"t": "1:30", "kind": "파밍", "label": "블루", "where": "상대 블루"}],
      "confidence": "seen",          // seen(미니맵이나 화면에서 봤다) | inferred(캠프 타이머, 킬 로그로 추론) | unknown
      "note": "..."
    }
  ],
  "pattern": "이 판에서 이 정글러가 턴을 쓴 방식 요약 2~3줄 (예: 성장 60%, 개입 30%. 상대 턴에 맞갱보다 반대편 교환을 택함)"
}
```
`kind`는 이 중 하나: `파밍`, `갱킹`, `카정`, `교전`, `오브젝트`, `시야`, `라인`(라인 CS 받기, 포탑 철거), `이동`, `귀환`, `사망`.
웹은 파밍 = 성장, 갱킹·카정·교전 = 개입, 오브젝트 = 오브젝트, 나머지 = 회색으로 칠하고 `label`을 막대 위에 쓴다. 행동의 길이는 다음 행동의 `t`까지다.

### operations (3층: 운영)
```json
{
  "objective_cycles": [
    {
      "objective": "용",            // 용 | 공허 유충 | 전령 | 바론 | 장로 | 아타칸 | 포탑 | 기타
      "spawn": "5:00",
      "prep_from": "4:00",
      "prep": "웨이브, 시야, 귀환 타이밍을 어떻게 준비했나",
      "decision": "싸움",           // 싸움 | 교환 | 포기 | 무혈
      "trade": "교환이나 포기라면 대신 얻은 것",
      "result": "우리 획득, 상대 원딜 킬",
      "taken_by": "ally",           // ally | enemy | none
      "source": "screen",
      "frames": []
    }
  ],
  "phases": [
    {"phase": "초반", "range": "0:00~14:00", "summary": "...", "points": ["..."]},
    {"phase": "중반", "range": "14:00~25:00", "summary": "...", "points": ["..."]},
    {"phase": "후반", "range": "25:00~", "summary": "...", "points": ["..."]}
  ],
  "turning_points": [
    {
      "ingame": "14:02", "vod": "1:37:20",
      "title": "바론 근처 시야 싸움 패배",
      "what": "무슨 일이 있었나",
      "why_decisive": "왜 흐름이 바뀌었나",
      "better": "이렇게 했어야 (스트리머 실수라면)",
      "frames": []
    }
  ],
  "plan_vs_result": "1층의 승리 조건과 정글 플랜이 실제로 어떻게 흘러갔나, 어디서 틀어졌나"
}
```

### fights (교전)
`tools/zoom.py`로 촘촘하게 본 교전. 2~5개.
```json
[
  {
    "id": "f1",
    "ingame": "10:05", "vod": "1:33:20",
    "title": "용 앞 2대2",
    "situation": "들어가기 전 상황",
    "choice": "스트리머가 한 행동",
    "reason": "...", "source": "screen", "quote": null,
    "fight": {
      "before": "체력, 레벨, 스펠, 합류 거리, 시야",
      "start": "누가 어떤 스킬로 시작했나",
      "flow": "핵심 스킬 적중, 스펠 순서, 타깃 선택",
      "decisive": "승패를 가른 이유",
      "uncertain": ["정지 화면이라 확실하지 않은 것"]
    },
    "background": ["이 교전을 이해하는 데 필요한 스킬 상호작용. 예: 칼리스타 궁은 아군을 붙잡았다 던지는 스킬이라, 붙잡힌 동안 레나타는 Q를 쓸 수 없다"],
    "concepts": ["objective-setup"],
    "rule": "이런 상황이면 → 이렇게",
    "frames": []
  }
]
```

### review (리플레이 피드백)
경기 뒤 스트리머가 리플레이를 돌려 보며 한 말. 스트리머가 직접 고른 장면이라 가장 좋은 교재다.
리플레이 화면의 인게임 시계로 이 판의 어느 순간인지 맞추고, 관련된 턴, 교전, 변곡점 id를 `refs`에 단다.
```json
{
  "available": true,
  "segments": [{"from": "1:59:00", "to": "2:08:00"}],
  "summary": "스트리머가 돌아보며 짚은 것 한두 줄",
  "comments": [
    {
      "id": "r1",
      "ingame": "14:02",           // 리플레이 화면 인게임 시계
      "vod": "2:01:30",            // 리플레이를 보던 VOD 시각
      "kind": "실수",              // 실수 | 잘한 점 | 대안 | 설명
      "said": "여기서 바론 와드 혼자 박으러 가면 안 됐어요",   // 발언 원문에 가깝게. 받아쓰기 오류는 고친다
      "point": "상대 정글 위치를 모를 때 혼자 시야 잡으러 가지 않는다",  // 플래티넘 이상이 가져갈 판단으로 정리
      "refs": ["t3", "p1"],        // 관련 턴, 교전(f), 변곡점(p), 오브젝트 사이클(o) id
      "frames": ["123_streamer/game2/review/frames/2-01-30.jpg"]
    }
  ]
}
```
턴, 교전, 변곡점에서 리플레이 발언을 근거로 쓰면 `source: "review"`, `quote`에 그 발언을 넣는다.

## kb/concepts.json (개념, 판을 넘어 누적)
```json
[
  {
    "id": "gank-decision",
    "name": "갱 각 판단",
    "category": "갱킹",
    "summary": "한 줄 요약",
    "definition": "정의와 왜 중요한지 (플래티넘 이상 기준, 기본 설명 생략)",
    "criteria": ["판단 기준"],
    "exceptions": ["예외와 조건"],
    "examples": [{"game_ref": "123_streamer/game2", "ref": "t2", "context": "솔로랭크", "note": "이 판에서 어떻게 나타났나"}]
  }
]
```
`ref`는 그 판 안의 턴(`t2`), 교전(`f1`), 오브젝트 사이클(`o1` = objective_cycles 첫 번째), 변곡점(`p1`), 라인(`lane-탑`) 중 하나.

## kb/rules.json (상황별 원칙)
```json
[
  {
    "id": "r-gank-pushed-lane",
    "category": "갱킹",
    "when": "라인이 우리 포탑 쪽으로 밀려 있고 상대 핵심 스펠이 빠져 있다",
    "then": "그 라인을 갱 1순위로 본다",
    "concepts": ["gank-decision"],
    "evidence": [{"game_ref": "123_streamer/game2", "ref": "t2", "context": "솔로랭크"}],
    "exceptions": []
  }
]
```
근거가 한 스트리머, 한 판뿐이면 웹이 "아직 가설"로 표시한다. 무리해서 일반화하지 않는다.

## kb/quizzes.json (복습 문제)
```json
[
  {
    "id": "q-123-game2-1",
    "type": "next_turn",             // plan(로딩 화면 보고 플랜) | next_turn(이번 턴 어떻게 쓸까) | objective(오브젝트 준비) | fight(교전 판단)
    "game_ref": "123_streamer/game2",
    "ref": "t2",
    "category": "턴 운영",
    "image": "123_streamer/game2/frames/1-26-30.jpg",   // 판단 직전 장면
    "ingame": "3:45",
    "situation": "문제 상황 설명. 턴 시작 상태(레벨, 골드, 라인, 상대 정글 마지막 위치, 다음 오브젝트)를 정답 힌트 없이",
    "question": "이번 턴을 어떻게 쓰시겠어요?",
    "answer": "스트리머가 실제로 한 선택",
    "explanation": "근거와 판단 기준, 다른 선택지와 비교",
    "concepts": ["gank-decision"]
  }
]
```

## kb/quiz_log.json — 웹이 쓴다. Claude는 읽기만 한다.
```json
{"q-123-game2-1": [{"date": "2026-11-20", "result": "O", "answer": "사용자 답"}]}
```
