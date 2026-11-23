import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type Coach, type CoachLesson, type CoachPoint, type DebriefDetail, type DebriefState, type SelfReview } from "../api";
import { Dots, ErrorView, isActive, JobSteps, Loading, PageHead, ResultBadge, usePoll, useToast } from "../ui";
import { MetricsCard } from "./Mine";

/** 남은 잠금 시간(초). 1초마다 다시 그린다 */
export function useRemaining(lockUntil: number | null | undefined) {
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    if (!lockUntil) return;
    const t = window.setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => window.clearInterval(t);
  }, [lockUntil]);
  return Math.max(0, Math.round((lockUntil ?? 0) - now));
}

export const clock = (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;

const GOAL = [["yes", "지켰어요"], ["partial", "일부만"], ["no", "못 지켰어요"], ["na", "상황이 없었어요"]] as const;

export default function Debrief() {
  const { id = "" } = useParams();
  const { data: d, error, reload } = usePoll(() => api.debrief(id), [id], (x) => !x?.coach && (isActive(x?.job) || !!x?.debrief?.locked), 4000);
  if (error) return <ErrorView message={error} />;
  if (!d) return <Loading />;
  const m = d.metrics;
  return (
    <div className="narrow-wrap debrief">
      <PageHead eyebrow={<Link to="/mine">‹ 내 게임</Link>} title="복기 시간"
        sub={[d.champion, m.minutes ? `${Math.round(m.minutes)}분` : null, d.played].filter(Boolean).join(" · ")}>
        <div className="row" style={{ marginTop: 12 }}><ResultBadge result={d.result} /></div>
      </PageHead>
      {d.debrief && <LockCard st={d.debrief} />}
      <MetricsCard m={m} />

      <section className="section">
        <h2 className="section-title"><span className="step-no">1</span>내 생각 먼저</h2>
        <SelfReviewForm d={d} onSaved={reload} />
      </section>

      <section className="section">
        <h2 className="section-title"><span className="step-no">2</span>AI 총평</h2>
        {d.coach ? <CoachView coach={d.coach} gameId={d.id} /> : <CoachPending d={d} onChange={reload} />}
      </section>

      {d.drills > 0 && (
        <section className="section">
          <h2 className="section-title"><span className="step-no">3</span>이 판 장면으로 다시 풀기</h2>
          <div className="card card-tight video-fetch">
            <div>
              <b>이 판의 판단 {d.drills}개{d.drills_bad ? ` (아쉬웠던 것 ${d.drills_bad}개 먼저)` : ""}</b>
              <div className="small">장면이 판단 직전에 멈추면 그때 했어야 할 선택을 골라요. 읽는 것보다 직접 떠올려야 다음 판에 나와요. 틀린 건 간격을 두고 다시 나와요.</div>
            </div>
            <Link className="btn btn-primary btn-sm" to={`/?start=${Math.min(d.drills, 12)}&game=${encodeURIComponent(d.game_ref)}`}>풀기</Link>
          </div>
        </section>
      )}

      <section className="section">
        <h2 className="section-title"><span className="step-no">{d.drills > 0 ? 4 : 3}</span>다음 판</h2>
        <NextStep d={d} onChange={reload} />
      </section>
    </div>
  );
}

function LockCard({ st }: { st: DebriefState }) {
  const left = useRemaining(st.lock_until);
  if (!st.lock_until) return null;
  return (
    <div className={`card lock-card ${left > 0 ? "on" : ""}`}>
      {left > 0 ? (
        <>
          <div className="lock-num">{clock(left)}</div>
          <div><b>뒤에 큐가 풀려요</b>
            <div className="small">판이 끝나면 바로 다음 판을 돌리지 않고 복기해요. 이 시간 동안 큐를 돌리면 앱이 취소해요.
              {st.blocked > 0 && ` 지금까지 ${st.blocked}번 막았어요.`}</div>
          </div>
        </>
      ) : (
        <div><b>이제 큐를 돌릴 수 있어요</b><div className="small">복기를 다 못 했으면 끝까지 보고 가요.</div></div>
      )}
    </div>
  );
}

function SelfReviewForm({ d, onSaved }: { d: DebriefDetail; onSaved: () => void }) {
  const init: SelfReview = d.self ?? { deaths: d.deaths.map((x) => ({ t: x.t })), moment: "", good: "", goal: d.goal?.followed ?? null };
  const [f, setF] = useState<SelfReview>(init);
  const [editing, setEditing] = useState(!d.self);
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  const deathAt = (t: string) => f.deaths.find((x) => x.t === t);
  const setDeath = (t: string, patch: object) =>
    setF({ ...f, deaths: d.deaths.map((x) => (x.t === t ? { ...(deathAt(x.t) ?? { t }), ...patch } : deathAt(x.t) ?? { t: x.t })) });

  if (!editing && d.self) {
    return (
      <div className="card card-tight">
        <ul className="bullets" style={{ margin: 0 }}>
          {d.self.deaths.filter((x) => x.reason).map((x) => <li key={x.t}><b>{x.t} 데스</b> {x.reason}</li>)}
          {d.self.moment && <li><b>가장 아쉬운 순간</b> {d.self.moment}</li>}
          {d.self.good && <li><b>잘한 것</b> {d.self.good}</li>}
        </ul>
        <div className="row" style={{ marginTop: 12 }}>
          <span className="caption">{d.coach ? "AI 총평이 내 복기와 비교했어요" : "AI 총평에서 내 복기와 비교해 드려요"}</span>
          <button className="btn btn-ghost btn-sm" onClick={() => setEditing(true)}>고치기</button>
        </div>
      </div>
    );
  }

  const save = async () => {
    setBusy(true);
    try {
      await api.saveSelfReview(d.id, f);
      toast.show("저장했어요");
      setEditing(false);
      onSaved();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card self-review">
      <p className="small" style={{ marginTop: 0 }}>AI 분석을 보기 전에 내가 본 이 판부터 적어요. 본 것과 놓친 것을 AI가 비교해 줘요.</p>
      {d.goal && (
        <div className="field">
          <div className="field-label">목표 "{d.goal.text}"</div>
          <div className="row">
            {GOAL.map(([k, label]) => <button key={k} className={`chip ${f.goal === k ? "on" : ""}`} onClick={() => setF({ ...f, goal: k })}>{label}</button>)}
          </div>
        </div>
      )}
      {d.deaths.length > 0 ? d.deaths.map((x) => (
        <div className="field" key={x.t}>
          <div className="field-label">{x.t} 데스 <span className="caption">{x.killer ? `${x.killer}에게` : ""}{x.assisters ? ` · ${x.assisters + 1}명이 왔어요` : ""}</span></div>
          <div className="row">
            {d.reasons.map((r) => (
              <button key={r} className={`chip ${deathAt(x.t)?.reason === r ? "on" : ""}`} onClick={() => setDeath(x.t, { reason: r })}>{r}</button>
            ))}
          </div>
        </div>
      )) : <p className="small">이 판은 데스가 없어요.</p>}
      <div className="field">
        <label className="field-label" htmlFor="moment">가장 아쉬운 순간</label>
        <input id="moment" className="input" placeholder="예) 8분 용 앞에서 바텀이 빠진 걸 못 보고 시작했어요" value={f.moment ?? ""}
          onChange={(e) => setF({ ...f, moment: e.target.value })} />
      </div>
      <div className="field">
        <label className="field-label" htmlFor="good">잘한 것</label>
        <input id="good" className="input" placeholder="예) 3분 바위게 싸움 전에 미드 주도권을 먼저 봤어요" value={f.good ?? ""}
          onChange={(e) => setF({ ...f, good: e.target.value })} />
      </div>
      <button className="btn btn-primary" disabled={busy} onClick={save}>{busy ? <Dots /> : "저장하기"}</button>
    </div>
  );
}

function CoachPending({ d, onChange }: { d: DebriefDetail; onChange: () => void }) {
  const [busy, setBusy] = useState(false);
  if (isActive(d.job)) {
    return (
      <div className="card">
        <p className="small" style={{ marginTop: 0 }}>Claude가 판 전체를 보고 있어요. 끝나면 여기에 총평이 나와요.</p>
        <JobSteps job={d.job!} />
      </div>
    );
  }
  const notJungle = d.role && d.role !== "정글";
  return (
    <div className="card card-tight">
      <p className="small" style={{ marginTop: 0 }}>
        {d.job?.status === "error" ? "분석이 중간에 멈췄어요." : notJungle ? "정글이 아닌 판은 자동으로 분석하지 않아요." : "아직 분석하지 않은 판이에요."}
      </p>
      <button className="btn btn-primary btn-sm" disabled={busy}
        onClick={async () => { setBusy(true); try { await api.analyzeMine(d.id); onChange(); } finally { setBusy(false); } }}>
        {busy ? <Dots /> : "분석하기"}
      </button>
    </div>
  );
}

const OUTCOME: Record<CoachLesson["outcome"], [string, string]> = {
  again: ["또 나왔어요", "badge-red"],
  first: ["새로 적었어요", "badge-grey"],
  better: ["나아졌어요", "badge-blue"],
  kept: ["잘 지켰어요", "badge-blue"],
};

/** 판 전체 총평. 복기 화면과 내 게임 분석 화면에서 같이 쓴다 */
export function CoachView({ coach, gameId }: { coach: Coach; gameId: string }) {
  const lessonFor = (p: CoachPoint) => coach.lessons?.find((l) => (p.ref && l.ref === p.ref) || (p.t && l.t === p.t) || l.title === p.title);
  const Point = ({ p, fix }: { p: CoachPoint; fix: boolean }) => {
    const le = lessonFor(p);
    return (
      <li className="coach-point">
        <div className="row" style={{ gap: 8 }}>
          {p.t && (p.ref ? <Link className="badge badge-grey" to={`/mine/${gameId}#${p.ref}`}>{p.t}</Link> : <span className="badge badge-grey">{p.t}</span>)}
          <b>{p.title}</b>
          {le && <span className={`badge ${OUTCOME[le.outcome][1]}`}>{OUTCOME[le.outcome][0]}</span>}
        </div>
        <p>{p.what}</p>
        {fix && p.better && <p className="better">→ {p.better}</p>}
        {p.pro && (
          <div className="pro-ref">
            <span className="card-label">프로는</span> {p.pro.text}
            {p.pro.vod && <> <Link to={`/vods/${encodeURIComponent(p.pro.vod)}/${p.pro.game ?? 1}${p.pro.ref ? `#${p.pro.ref}` : ""}`}>장면 보기 →</Link></>}
          </div>
        )}
      </li>
    );
  };
  return (
    <div className="coach">
      <div className="card card-blue"><div className="card-label">한 줄 총평</div><div className="coach-headline">{coach.headline}</div></div>
      {coach.fixes?.length > 0 && (
        <>
          <h3 className="coach-sub">고칠 것</h3>
          <ol className="coach-list">{coach.fixes.map((p, i) => <Point key={i} p={p} fix />)}</ol>
        </>
      )}
      {coach.keeps?.length > 0 && (
        <>
          <h3 className="coach-sub">지킬 것</h3>
          <ul className="coach-list">{coach.keeps.map((p, i) => <Point key={i} p={p} fix={false} />)}</ul>
        </>
      )}
      {coach.self_check && <div className="card card-tight" style={{ marginTop: 16 }}><div className="card-label">내 복기와 비교</div><p style={{ margin: 0 }}>{coach.self_check}</p></div>}
    </div>
  );
}

function NextStep({ d, onChange }: { d: DebriefDetail; onChange: () => void }) {
  const [set, setSet] = useState(false);
  const left = useRemaining(d.debrief?.lock_until);
  const ng = d.next_goal;
  return (
    <div>
      {ng ? (
        <div className="card card-blue">
          <div className="card-label">다음 판 목표 추천</div>
          <div className="goal-text">{ng.when} → {ng.then}</div>
          {ng.why && <p className="small">{ng.why}</p>}
          <button className="btn btn-primary btn-sm" disabled={set} onClick={async () => { await api.setGoal(`${ng.when} → ${ng.then}`, ng.rule_id); setSet(true); }}>
            {set ? "다음 판 목표로 정했어요" : "다음 판 목표로 정하기"}
          </button>
        </div>
      ) : <p className="small">총평이 나오면 다음 판 목표를 추천해 드려요.</p>}
      <div className="row" style={{ marginTop: 16 }}>
        {d.analyzed && <Link className="btn btn-ghost" to={`/mine/${d.id}`}>전체 분석 보기</Link>}
        {d.debrief?.done ? <span className="caption">복기를 마쳤어요{left > 0 ? ` · 큐는 ${clock(left)} 뒤에 풀려요` : ""}</span> : (
          <button className="btn btn-secondary" onClick={async () => { await api.finishDebrief(d.id); onChange(); }}>복기 끝내기</button>
        )}
      </div>
    </div>
  );
}
