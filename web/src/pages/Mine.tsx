import { useState } from "react";
import { Link } from "react-router-dom";
import { api, type AgentInfo, type GameMetrics, type Goal, type Goals, type MyGame, type MyGameDetail } from "../api";
import { Dots, ErrorView, isActive, JobSteps, Loading, PageHead, ResultBadge, usePoll, useToast } from "../ui";

const FOLLOWED: Record<string, { label: string; cls: string }> = {
  yes: { label: "목표 지킴", cls: "badge-blue" },
  partial: { label: "일부 지킴", cls: "badge-orange" },
  no: { label: "못 지킴", cls: "badge-red" },
  na: { label: "상황 없었음", cls: "badge-grey" },
};

const mmss = (s: number | null | undefined) => (s == null ? "" : `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`);

export default function Mine() {
  const games = usePoll(api.myGames, [], (d) => !!d?.some((g) => isActive(g.job)), 4000);
  const agent = usePoll(api.agent, [], () => true, 5000);
  const goals = usePoll(api.goals, [], () => false);

  if (games.error) return <ErrorView message={games.error} />;
  if (!games.data || !agent.data || !goals.data) return <Loading />;

  return (
    <div className="layout">
      <div>
        <PageHead title="내 게임" sub="앱을 켜 두면 롤 게임을 자동으로 녹화하고, 판이 끝나면 바로 분석해요." />
        <AgentCard info={agent.data} onChange={agent.reload} />
        <GoalCard goals={goals.data} onChange={goals.reload} />
        <div className="mobile-only section"><WeekStats /></div>
        <section className="section">
          <h2 className="section-title">최근 게임</h2>
          {games.data.length === 0 ? (
            <div className="card card-tight"><p className="small" style={{ margin: 0 }}>아직 녹화한 게임이 없어요. 에이전트를 켜고 한 판 해 보세요.</p></div>
          ) : (
            <div className="list">{games.data.map((g) => <GameRow key={g.id} g={g} />)}</div>
          )}
        </section>
      </div>
      <aside className="aside"><WeekStats /></aside>
    </div>
  );
}

/* ---------------- 녹화 에이전트 ---------------- */
function AgentCard({ info, onChange }: { info: AgentInfo; onChange: () => void }) {
  const [token, setToken] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(false);
  const toast = useToast();
  const st = info.status;

  const makeToken = async () => {
    setBusy(true);
    try { setToken((await api.agentToken()).token); setOpen(true); onChange(); } finally { setBusy(false); }
  };
  const copy = (t: string) => { void navigator.clipboard?.writeText(t).then(() => toast.show("복사했어요")); };
  const server = info.server;
  const steps = token ? [
    { title: "Python과 ffmpeg 설치 (처음 한 번)", cmd: "winget install -e Python.Python.3.12 Gyan.FFmpeg" },
    { title: "녹화 에이전트 받기", cmd: `curl.exe -o recorder.py ${server}/api/agent/recorder.py` },
    { title: "실행 (롤을 하는 동안 켜 두기)", cmd: `python recorder.py --server ${server} --token ${token}` },
  ] : [];

  return (
    <div className={`card agent-card ${info.online ? (st?.state === "recording" ? "rec" : "on") : ""}`}>
      <div className="agent-head">
        <span className={`agent-dot ${info.online ? st?.state : "off"}`} />
        <div style={{ flex: 1 }}>
          <div className="agent-title">
            {!info.online ? (info.tokens.length ? "녹화 에이전트가 꺼져 있어요" : "녹화 에이전트를 연결해 주세요")
              : st?.state === "recording" ? `녹화 중 · ${st.champion ?? "게임"} ${mmss(st.game_time)}`
              : "게임을 기다리는 중이에요"}
          </div>
          <div className="small">
            {!info.online ? "게임하는 PC에서 에이전트를 켜 두면 게임이 시작될 때 알아서 녹화해요."
              : `${st?.platform} · 에이전트 ${st?.version}${st?.pending ? ` · 올릴 녹화 ${st.pending}개` : ""}`}
          </div>
        </div>
        {!info.online && !token && (
          <button className="btn btn-primary btn-sm" onClick={makeToken} disabled={busy}>{busy ? <Dots /> : info.tokens.length ? "다시 연결" : "연결하기"}</button>
        )}
      </div>

      {token && open && (
        <div className="agent-setup">
          <p className="small">게임하는 Windows PC의 PowerShell에서 차례로 실행해 주세요. 토큰은 지금만 보여요.</p>
          <ol>
            {steps.map((s, i) => (
              <li key={i}>
                <div className="agent-step">{s.title}</div>
                <div className="cmd"><code>{s.cmd}</code><button onClick={() => copy(s.cmd)}>복사</button></div>
              </li>
            ))}
          </ol>
          <details className="small">
            <summary>연결이 안 되면</summary>
            <ul>
              <li>이 서버가 다른 PC에서 접속되게 켜져 있어야 해요: 서버 PC에서 <code>HOST=0.0.0.0 ./run.sh</code></li>
              <li>두 PC가 같은 공유기(네트워크)에 있어야 해요. 서버 주소: <code>{server}</code></li>
              <li>롤은 <b>테두리 없음</b> 창 모드를 권장해요. 전체 화면에서 검게 녹화되면 바꿔 주세요.</li>
              <li>모니터가 여러 개면 <code>--screen 1</code>처럼 롤이 뜨는 모니터 번호를 넣어 주세요.</li>
            </ul>
          </details>
          <button className="btn btn-ghost btn-sm" onClick={() => setOpen(false)}>닫기</button>
        </div>
      )}
      {toast.node}
      {info.tokens.length > 0 && !token && (
        <button className="link-btn small" onClick={async () => { if (confirm("연결된 에이전트를 모두 끊을까요? 다시 연결하려면 새 토큰이 필요해요.")) { await api.revokeAgent(); onChange(); } }}>
          연결 끊기
        </button>
      )}
    </div>
  );
}

/* ---------------- 다음 판 목표 ---------------- */
function GoalCard({ goals, onChange }: { goals: Goals; onChange: () => void }) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const active = goals.active;
  const save = async (t: string, rule?: string | null) => {
    setBusy(true);
    try { await api.setGoal(t, rule); setEditing(false); setText(""); onChange(); } finally { setBusy(false); }
  };
  const last = goals.history.filter((g) => g.followed).slice(0, 10);
  const kept = last.filter((g) => g.followed === "yes").length;

  return (
    <section className="section">
      <h2 className="section-title">다음 판 목표</h2>
      <p className="small" style={{ marginTop: -8 }}>판 중에 떠올릴 "이러면 → 이렇게" 하나만 정해요. 판이 끝나면 지켰는지 분석에서 확인해요.</p>
      {active && !editing ? (
        <div className="card card-blue goal-active">
          <div className="card-label">다음 판에서 지킬 것</div>
          <div className="goal-text">{active.text}</div>
          <div className="row" style={{ marginTop: 12 }}>
            <button className="btn btn-ghost btn-sm" onClick={() => setEditing(true)}>바꾸기</button>
            <button className="btn btn-ghost btn-sm" onClick={async () => { await api.clearGoal(); onChange(); }}>목표 없이 하기</button>
          </div>
        </div>
      ) : (
        <div className="card card-tight">
          <div className="goal-suggest">
            {goals.suggestions.map((s) => (
              <button key={s.rule_id} className="goal-opt" disabled={busy} onClick={() => save(`${s.when} → ${s.then}`, s.rule_id)}>
                <span className="badge badge-grey">{s.category}</span>
                {s.why && <span className="badge badge-orange">{s.why}</span>}
                <span className="goal-when">{s.when}</span>
                <span className="goal-then">→ {s.then}</span>
              </button>
            ))}
          </div>
          <div className="goal-free">
            <input className="input" placeholder="직접 쓰기: 예) 바텀이 밀려 있으면 → 갱 대신 위쪽 캠프로" value={text}
              onChange={(e) => setText(e.target.value)} onKeyDown={(e) => e.key === "Enter" && text.trim() && save(text.trim())} />
            <button className="btn btn-primary" disabled={!text.trim() || busy} onClick={() => save(text.trim())}>정하기</button>
          </div>
          {editing && <button className="link-btn small" onClick={() => setEditing(false)}>취소</button>}
        </div>
      )}
      {last.length > 0 && <p className="caption" style={{ marginTop: 8 }}>최근 목표 {last.length}판 중 {kept}판 지켰어요.</p>}
    </section>
  );
}

/* ---------------- 게임 목록 ---------------- */
function MetricLine({ m }: { m: GameMetrics }) {
  const parts = [
    m.kda && `${m.kda[0]}/${m.kda[1]}/${m.kda[2]}`,
    m.cs10 != null && `10분 CS ${m.cs10}`,
    `14분 전 데스 ${m.deaths_before_14}`,
    m.kp != null && `킬 관여 ${Math.round(m.kp * 100)}%`,
  ].filter(Boolean);
  return <>{parts.join(" · ")}</>;
}

function GameRow({ g }: { g: MyGame }) {
  const running = isActive(g.job);
  return (
    <Link to={`/mine/${g.id}`} className="list-row">
      <div className="list-body">
        <div className="list-title">
          {g.champion ?? "?"} {g.role && g.role !== "정글" && <span className="badge badge-grey">{g.role}</span>} <ResultBadge result={g.result} />
          {g.goal?.followed && <span className={`badge ${FOLLOWED[g.goal.followed].cls}`}>{FOLLOWED[g.goal.followed].label}</span>}
        </div>
        <div className="list-desc">{g.played} · {g.metrics.minutes ? `${Math.round(g.metrics.minutes)}분` : ""} · <MetricLine m={g.metrics} /></div>
      </div>
      <span className="small" style={{ whiteSpace: "nowrap" }}>
        {running ? <>분석 중 <Dots /></> : g.analyzed ? "분석 보기 ›" : g.job?.status === "error" ? "분석 실패" : "분석 전"}
      </span>
    </Link>
  );
}

function WeekStats() {
  const { data } = usePoll(api.myStats, [], () => false);
  if (!data || data.weeks.length === 0) {
    return <div className="card card-tight"><div className="card-label">주간 지표</div><p className="small" style={{ margin: 0 }}>정글 판이 쌓이면 주마다 10분 CS, 14분 전 데스, 오브젝트 점유율을 보여 드려요.</p></div>;
  }
  const rows = [...data.weeks].reverse().slice(0, 4);
  return (
    <div className="card card-tight">
      <div className="card-label">주간 지표 (정글 판)</div>
      <table className="week-table">
        <thead><tr><th>주</th><th>판</th><th>승률</th><th>10분 CS</th><th>14분 전 데스</th><th>오브젝트</th></tr></thead>
        <tbody>
          {rows.map((w) => (
            <tr key={w.week}>
              <td>{w.week.slice(5).replace("-", "/")}</td><td>{w.games}</td><td>{Math.round(w.win_rate * 100)}%</td>
              <td>{w.cs10 ?? "–"}</td><td>{w.deaths_before_14 ?? "–"}</td>
              <td>{w.objective_share != null ? `${Math.round(w.objective_share * 100)}%` : "–"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ---------------- 분석 전 화면, 목표 판정 (Game 페이지에서 씀) ---------------- */
export function MinePending({ g, onChange }: { g: MyGameDetail; onChange: () => void }) {
  const [busy, setBusy] = useState(false);
  const running = isActive(g.job);
  const m = g.metrics;
  return (
    <div className="narrow-wrap">
      <PageHead eyebrow={<Link to="/mine">‹ 내 게임</Link>} title={`${g.champion ?? "내 게임"}`} sub={`${g.played} · ${m.minutes ? `${Math.round(m.minutes)}분` : ""}`}>
        <div className="row" style={{ marginTop: 12 }}><ResultBadge result={g.result} />{g.role && <span className="badge badge-grey">{g.role}</span>}</div>
      </PageHead>
      <MetricsCard m={m} />
      {g.goal && <div className="card card-tight" style={{ marginTop: 16 }}><div className="card-label">이 판의 목표</div><div className="goal-text">{g.goal.text}</div><p className="small" style={{ marginBottom: 0 }}>분석이 끝나면 지켰는지 판정해 드려요.</p></div>}
      {g.job && <div className="card" style={{ marginTop: 16 }}><JobSteps job={g.job} /></div>}
      {!running && (
        <div className="card card-tight" style={{ marginTop: 16 }}>
          <p className="small" style={{ marginTop: 0 }}>
            {g.role && g.role !== "정글" ? "정글이 아닌 판은 자동으로 분석하지 않아요." : g.job?.status === "error" ? "분석이 중간에 멈췄어요." : "아직 분석하지 않은 판이에요."}
            {" "}분석하면 판단 포인트가 내 훈련 문제로 들어가요.
          </p>
          <button className="btn btn-primary" disabled={busy} onClick={async () => { setBusy(true); try { await api.analyzeMine(g.id); onChange(); } finally { setBusy(false); } }}>분석하기</button>
        </div>
      )}
    </div>
  );
}

export function MetricsCard({ m }: { m: GameMetrics }) {
  const obj = Object.entries(m.objectives ?? {});
  return (
    <div className="stats metrics">
      <div className="stat"><div className="stat-num">{m.kda ? m.kda.join("/") : "–"}</div><div className="stat-label">KDA</div></div>
      <div className="stat"><div className="stat-num">{m.cs10 ?? "–"}</div><div className="stat-label">10분 CS</div></div>
      <div className="stat"><div className="stat-num">{m.deaths_before_14}</div><div className="stat-label">14분 전 데스</div></div>
      <div className="stat"><div className="stat-num">{m.early_takedowns}</div><div className="stat-label">8분 전 킬 관여</div></div>
      {obj.length > 0 && (
        <div className="stat stat-wide">
          <div className="obj-row">{obj.map(([k, v]) => <span key={k}>{k} <b>{v.ally}</b>:{v.enemy}</span>)}</div>
          <div className="stat-label">오브젝트 (우리:상대)</div>
        </div>
      )}
      {m.late_start && <p className="caption" style={{ gridColumn: "1 / -1" }}>게임 도중부터 녹화돼서 앞부분 기록이 없어요.</p>}
    </div>
  );
}

export function GoalVerdict({ goal, check, onChange }: { goal: Goal | null; check?: { followed: string; evidence?: string; moments?: { t: string; followed: boolean; note?: string }[] }; onChange: () => void }) {
  if (!goal) return null;
  const cur = goal.followed ?? check?.followed;
  const set = async (f: string) => { await api.checkGoal(goal.id, f, goal.note ?? check?.evidence); onChange(); };
  return (
    <div className="card card-tight goal-verdict">
      <div className="card-label">이 판의 목표</div>
      <div className="goal-text">{goal.text}</div>
      {cur && <span className={`badge ${FOLLOWED[cur].cls}`} style={{ marginTop: 8 }}>{FOLLOWED[cur].label}</span>}
      {(goal.note || check?.evidence) && <p className="small">{goal.note || check?.evidence}</p>}
      {check?.moments && check.moments.length > 0 && (
        <ul className="moments">{check.moments.map((x, i) => <li key={i}><b>{x.t}</b> {x.followed ? "✓" : "✕"} {x.note}</li>)}</ul>
      )}
      <div className="row" style={{ marginTop: 8 }}>
        <span className="caption">판정이 다르면 직접 고쳐 주세요</span>
        {Object.entries(FOLLOWED).map(([k, v]) => (
          <button key={k} className={`chip ${cur === k ? "on" : ""}`} style={{ padding: "4px 10px", fontSize: 13 }} onClick={() => set(k)}>{v.label}</button>
        ))}
      </div>
    </div>
  );
}
