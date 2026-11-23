import { useEffect, useMemo, useState } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import { api, secs, type GameDetail, type Analysis, type Concept, type Decision, type Draft, type Lane, type Pick, type ReviewComment, type Source, type Turn } from "../api";
import { ErrorView, FrameStrip, isActive, Loading, PageHead, ResultBadge, SourceBadge, usePoll } from "../ui";
import { GoalVerdict, MetricsCard, MinePending } from "./Mine";
import { CoachView } from "./Debrief";
import Timeline, { GROUP_LABEL, Legend, TurnBar, groupOf, timeShare } from "./game/Timeline";
import { PlayerProvider } from "./game/Player";
import { ClipsProvider, PlayButton, buildClips, useClips } from "./game/clips";

type Tab = "summary" | "plan" | "turns" | "ops" | "fights" | "review";
const TABS: [Tab, string][] = [["summary", "요약"], ["plan", "플랜"], ["turns", "턴"], ["ops", "운영"], ["fights", "교전"], ["review", "피드백"]];

/** 이 id(t3, f1, p1...)를 짚은 리플레이 발언 */
const reviewsFor = (a: Analysis, id: string) => (a.review?.comments ?? []).filter((c) => c.refs?.includes(id));

/** 해시(#t2, #f1, #o1, #p1, #lane-탑)가 어느 탭에 있는지 */
function tabFor(ref: string): Tab {
  if (ref.startsWith("lane-")) return "plan";
  if (ref.startsWith("t")) return "turns";
  if (ref.startsWith("f")) return "fights";
  if (ref.startsWith("o") || ref.startsWith("p")) return "ops";
  if (ref.startsWith("r")) return "review";
  return "summary";
}

export default function GamePage() {
  const { dir: vodDir = "", n = "1", id: mineId } = useParams();
  const { hash } = useLocation();
  const ref = decodeURIComponent(hash.slice(1));
  // 내 게임(/mine/:id)도 같은 화면으로 본다. 분석 전이면 진행 상황과 지표를 보여준다
  const { data: mine, reload: reloadMine } = usePoll(() => (mineId ? api.myGame(mineId) : Promise.resolve(null)), [mineId],
    (d) => !!d && isActive(d.job), 4000);
  const { data: vodData, error } = usePoll(() => (mineId ? Promise.resolve(null) : api.game(vodDir, Number(n))), [vodDir, n, mineId], () => false);
  const data = (mineId ? (mine?.analysis ? mine : null) : vodData) as GameDetail | null | undefined;
  const dir = data?.vod.dir ?? vodDir;
  const { data: kb } = usePoll(api.kb, [], () => false);
  const [tab, setTab] = useState<Tab>(ref ? tabFor(ref) : "summary");
  const [turn, setTurn] = useState<string | null>(ref.startsWith("t") ? ref : null);
  const concepts = useMemo(() => new Map((kb?.concepts ?? []).map((c) => [c.id, c])), [kb]);
  const clips = useMemo(() => (data && (data.analysis.version ?? 1) >= 2 ? buildClips(data.analysis, dir, Number(n), data.meta) : null), [data, dir, n]);

  useEffect(() => {
    if (!ref || !data) return;
    setTab(tabFor(ref));
    if (ref.startsWith("t")) setTurn(ref);
    window.setTimeout(() => document.getElementById(ref)?.scrollIntoView({ behavior: "smooth", block: "start" }), 80);
  }, [ref, data]);

  if (error) return <ErrorView message={error} />;
  if (mineId && mine && !mine.analysis) return <MinePending g={mine} onChange={reloadMine} />;
  if (!data) return <Loading />;
  const a = data.analysis;
  if ((a.version ?? 1) < 2) {
    return <ErrorView message="예전 형식으로 분석된 판이에요. 영상 화면에서 '다시 분석'을 눌러 주세요." />;
  }

  const selectTurn = (id: string) => {
    setTurn(id);
    document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  return (
    <PlayerProvider>
    <ClipsProvider clips={clips}>
      <PageHead eyebrow={mineId ? <Link to="/mine">‹ 내 게임</Link> : <Link to={`/vods/${encodeURIComponent(dir)}`}>‹ {data.vod.uploader || "영상"}</Link>} title={`${a.champion}${a.enemy_jungler ? ` vs ${a.enemy_jungler}` : ""}`}>
        <div className="row" style={{ marginTop: 12 }}>
          <ResultBadge result={a.result} />
          {a.context && a.context !== "솔로랭크" && <span className="badge badge-orange">{a.context}</span>}
          <span className="small">{(mine ? [mine.played, a.length] : [a.streamer, `${data.game.n}판`, a.length]).filter(Boolean).join(" · ")}</span>
        </div>
      </PageHead>
      {mine && (
        <div className="own-head">
          <MetricsCard m={mine.metrics} />
          {a.coach && <CoachView coach={a.coach} gameId={mine.id} />}
          <GoalVerdict goal={mine.goal} check={a.goal_check} onChange={reloadMine} />
          {a.next_goal && (
            <div className="card card-blue">
              <div className="card-label">다음 판 목표 추천</div>
              <div className="goal-text">{a.next_goal.when} → {a.next_goal.then}</div>
              {a.next_goal.why && <p className="small">{a.next_goal.why}</p>}
              <NextGoalButton text={`${a.next_goal.when} → ${a.next_goal.then}`} rule={a.next_goal.rule_id} />
            </div>
          )}
        </div>
      )}

      <div className="layout">
        <div>
          <div className="tabs" role="tablist">
            {TABS.filter(([k]) => k !== "review" || a.review?.available).map(([k, label]) => (
              <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? "on" : ""} onClick={() => setTab(k)}>{label}</button>
            ))}
          </div>
          {tab === "summary" && <Summary a={a} concepts={concepts} go={setTab} />}
          {tab === "plan" && <PlanView a={a} />}
          {tab === "turns" && <TurnsView a={a} selected={turn} onSelect={selectTurn} />}
          {tab === "ops" && <OpsView a={a} />}
          {tab === "fights" && <FightsView a={a} concepts={concepts} />}
          {tab === "review" && <ReviewView a={a} />}
        </div>
        <Rail a={a} go={setTab} tab={tab} />
      </div>
    </ClipsProvider>
    </PlayerProvider>
  );
}

/* ---------------- 오른쪽 패널 (데스크톱) ---------------- */
function Rail({ a, go, tab }: { a: Analysis; go: (t: Tab) => void; tab: Tab }) {
  const turns = a.turns?.ally ?? [];
  const count = (v: string) => turns.filter((t) => t.verdict === v).length;
  const objs = a.operations?.objective_cycles ?? [];
  const { acc, sum } = timeShare(turns);
  return (
    <aside className="aside">
      {a.review?.available && tab !== "review" && (
        <button className="card card-tight" style={{ width: "100%", textAlign: "left", border: 0, cursor: "pointer", marginBottom: 12, background: "var(--orange-bg)" }} onClick={() => go("review")}>
          <div className="card-label" style={{ color: "var(--orange)" }}>리플레이 피드백 {a.review.comments?.length ?? 0}개</div>
          <div style={{ fontWeight: 600, fontSize: 15 }}>{a.review.summary ?? "경기 뒤 스트리머가 직접 짚은 장면"}</div>
        </button>
      )}
      {a.plan?.jungle_plan && tab !== "plan" && (
        <div className="card card-blue card-tight">
          <div className="card-label">정글 플랜</div>
          <div style={{ fontWeight: 600, fontSize: 16 }}>{a.plan.jungle_plan}</div>
        </div>
      )}
      <div className="card card-tight">
        <button className="row" style={{ border: 0, background: "none", padding: 0, width: "100%", cursor: "pointer" }} onClick={() => go("turns")}>
          <b>{turns.length}턴</b><span className="spacer" />
          <span className="badge badge-blue">이득 {count("이득")}</span>
          <span className="badge badge-grey">교환 {count("교환")}</span>
          <span className="badge badge-red">손해 {count("손해")}</span>
        </button>
        {turns.length > 0 && (
          <>
            <div className="share">
              {(["grow", "act", "obj", "etc"] as const).filter((g) => acc[g] > 0).map((g) => (
                <span key={g} className={`g-${g}`} style={{ width: `${(acc[g] / sum) * 100}%` }} />
              ))}
            </div>
            <div className="legend" style={{ marginBottom: 0, fontSize: 12 }}>
              {(["grow", "act", "obj"] as const).map((g) => (
                <span key={g}><i className={`sw sw-${g}`} />{GROUP_LABEL[g]} {Math.round((acc[g] / sum) * 100)}%</span>
              ))}
            </div>
          </>
        )}
        <hr className="divider" style={{ margin: "16px 0" }} />
        <button className="row" style={{ border: 0, background: "none", padding: 0, width: "100%", cursor: "pointer" }} onClick={() => go("ops")}>
          <b>오브젝트</b><span className="spacer" />
          <span className="small">우리 {objs.filter((o) => o.taken_by === "ally").length} : {objs.filter((o) => o.taken_by === "enemy").length} 상대</span>
        </button>
      </div>
      {a.takeaways?.length > 0 && (
        <div className="aside-block" style={{ marginTop: 24 }}>
          <div className="card-label">가져갈 것</div>
          <ol className="numbered" style={{ fontSize: 15 }}>{a.takeaways.map((t, i) => <li key={i}><span>{t}</span></li>)}</ol>
        </div>
      )}
    </aside>
  );
}

/* ---------------- 요약 ---------------- */
function Summary({ a, concepts, go }: { a: Analysis; concepts: Map<string, Concept>; go: (t: Tab) => void }) {
  const turns = a.turns?.ally ?? [];
  const verdicts = { 이득: 0, 교환: 0, 손해: 0 } as Record<string, number>;
  turns.forEach((t) => (verdicts[t.verdict] = (verdicts[t.verdict] ?? 0) + 1));
  const objs = a.operations?.objective_cycles ?? [];
  const objAlly = objs.filter((o) => o.taken_by === "ally").length;
  const objEnemy = objs.filter((o) => o.taken_by === "enemy").length;
  const { acc, sum } = timeShare(turns);

  return (
    <div>
      {a.plan?.jungle_plan && (
        <div className="card card-blue mobile-only" style={{ marginBottom: 48 }}>
          <div className="card-label">이 판의 정글 플랜</div>
          <div style={{ fontWeight: 600 }}>{a.plan.jungle_plan}</div>
        </div>
      )}

      <section className="mobile-only" style={{ marginBottom: 48 }}>
        <h2 className="section-title">이 판에서 가져갈 것</h2>
        <ol className="numbered">{a.takeaways.map((t, i) => <li key={i}><span>{t}</span></li>)}</ol>
      </section>

      <section>
        <div className="stats">
          <button className="stat" style={{ border: 0, textAlign: "left", cursor: "pointer" }} onClick={() => go("turns")}>
            <div className="stat-num">{turns.length}턴</div>
            <div className="stat-label">이득 {verdicts["이득"]} · 교환 {verdicts["교환"]} · 손해 {verdicts["손해"]}</div>
          </button>
          <button className="stat" style={{ border: 0, textAlign: "left", cursor: "pointer" }} onClick={() => go("ops")}>
            <div className="stat-num">{objAlly} : {objEnemy}</div>
            <div className="stat-label">오브젝트 (우리 : 상대)</div>
          </button>
          <button className="stat" style={{ border: 0, textAlign: "left", cursor: "pointer" }} onClick={() => go("fights")}>
            <div className="stat-num">{a.fights?.length ?? 0}</div>
            <div className="stat-label">뜯어본 교전</div>
          </button>
        </div>
      </section>

      {turns.length > 0 && (
        <section className="section">
          <h2 className="section-title">시간을 어디에 썼나</h2>
          <div className="share" role="img" aria-label="시간 비율">
            {(["grow", "act", "obj", "etc"] as const).filter((g) => acc[g] > 0).map((g) => (
              <span key={g} className={`g-${g}`} style={{ width: `${(acc[g] / sum) * 100}%` }} />
            ))}
          </div>
          <div className="legend">
            {(["grow", "act", "obj", "etc"] as const).map((g) => (
              <span key={g}><i className={`sw sw-${g}`} />{GROUP_LABEL[g]} {Math.round((acc[g] / sum) * 100)}%</span>
            ))}
          </div>
          {a.turns.pattern && <p style={{ margin: 0 }}>{a.turns.pattern}</p>}
        </section>
      )}

      <section className="section">
        <h2 className="section-title">한눈에 보기</h2>
        <ul className="bullets">{a.summary.map((s, i) => <li key={i}>{s}</li>)}</ul>
      </section>

      {(a.new_concepts?.length ?? 0) > 0 && (
        <section className="section">
          <h2 className="section-title">이 판에서 나온 개념</h2>
          <div className="row">
            {a.new_concepts!.map((id) => <Link key={id} to={`/concepts/${id}`} className="chip">{concepts.get(id)?.name ?? id}</Link>)}
          </div>
        </section>
      )}
    </div>
  );
}

/* ---------------- 플랜 ---------------- */
const VERDICT: Record<Lane["verdict"], [string, string]> = {
  gank: ["갈 라인", "badge-blue"],
  protect: ["지킬 라인", "badge-orange"],
  ignore: ["버릴 라인", "badge-grey"],
};
const PRIORITY: Record<Lane["priority"], string> = { ally: "우리 주도권", enemy: "상대 주도권", even: "비슷" };

function Why({ text, source, quote }: { text: string; source?: Source; quote?: string | null }) {
  return (
    <>
      <p style={{ margin: 0 }}>{text} {source && <SourceBadge source={source} />}</p>
      {quote && <div className="quote">“{quote}”</div>}
    </>
  );
}

function PlanView({ a }: { a: Analysis }) {
  const p = a.plan;
  if (!p) return <p className="small">플랜 정보가 없어요.</p>;
  return (
    <div>
      <div className="card card-blue">
        <div className="card-label">정글 플랜</div>
        <div style={{ fontWeight: 700, fontSize: 18 }}>{p.jungle_plan}</div>
        {p.plan_quote && <div className="quote" style={{ background: "rgba(255,255,255,.6)" }}>“{p.plan_quote}” <SourceBadge source={p.plan_source} /></div>}
      </div>

      {p.draft?.available && (
        <section className="section">
          <h2 className="section-title">밴픽</h2>
          <DraftView d={p.draft} />
        </section>
      )}

      {p.lanes?.length > 0 && (
        <section className="section">
          <h2 className="section-title">라인 지도</h2>
          <p className="section-sub">구도를 보고 정한 갈 라인, 지킬 라인, 버릴 라인이에요</p>
          <div className="stack lanes-grid">
            {p.lanes.map((l) => (
              <div key={l.lane} id={`lane-${l.lane}`} className="lane-card">
                <div className="lane-head">
                  <span className="lane-name">{l.lane}</span>
                  <span className={`badge ${VERDICT[l.verdict]?.[1] ?? "badge-grey"}`}>{VERDICT[l.verdict]?.[0] ?? l.verdict}</span>
                  <span className="caption" style={{ marginLeft: "auto" }}>{PRIORITY[l.priority] ?? l.priority}</span>
                </div>
                <div style={{ fontWeight: 600, marginBottom: 12 }}>{l.ally} <span className="vs">vs</span> {l.enemy}</div>
                <dl className="kv">
                  <dt>스파이크</dt><dd>{l.spikes}</dd>
                  <dt>갱 호응</dt><dd>{l.gank_setup}</dd>
                  <dt>다이브</dt><dd>{l.dive}</dd>
                  <dt>판단</dt><dd>{l.reason} <SourceBadge source={l.source} /></dd>
                  <dt>실제</dt><dd>{l.actual}</dd>
                </dl>
                <Background items={l.background} />
              </div>
            ))}
          </div>
        </section>
      )}

      {p.junglers && (
        <section className="section">
          <h2 className="section-title">두 정글</h2>
          <div className="draft-grid">
            {(["ally", "enemy"] as const).map((side) => {
              const j = p.junglers![side];
              return (
                <div key={side} className={`team ${side}`}>
                  <div className="team-title">{side === "ally" ? "우리" : "상대"} · {j.champion}</div>
                  <dl className="kv" style={{ gridTemplateColumns: "56px 1fr", fontSize: 15 }}>
                    <dt>초반</dt><dd>{j.early}</dd>
                    <dt>첫 동선</dt><dd>{j.first_path} <SourceBadge source={j.source} /></dd>
                  </dl>
                </div>
              );
            })}
          </div>
        </section>
      )}

      {p.win_conditions && (
        <section className="section">
          <h2 className="section-title">이기는 방법</h2>
          <dl className="kv"><dt>우리</dt><dd>{p.win_conditions.ally}</dd><dt>상대</dt><dd>{p.win_conditions.enemy}</dd></dl>
        </section>
      )}
      {p.loading_frame && <FrameStrip frames={[p.loading_frame]} />}
    </div>
  );
}

function DraftView({ d }: { d: Draft }) {
  const me = d.my_pick?.champion;
  const team = (side: "ally" | "enemy", title: string) => {
    const picks: Pick[] = [...(d.picks?.[side] ?? [])].sort((x, y) => x.order - y.order);
    return (
      <div className={`team ${side}`}>
        <div className="team-title">{title}</div>
        {(d.bans?.[side]?.length ?? 0) > 0 && <div className="bans" aria-label="밴">{d.bans![side].map((b) => <span key={b}>{b}</span>)}</div>}
        {picks.map((p) => (
          <div key={p.champion} className={`pick ${side === "ally" && p.champion === me ? "me" : ""}`}>
            <span className="pick-order">{p.order}</span><span>{p.champion}</span><span className="pick-role">{p.role}</span>
          </div>
        ))}
      </div>
    );
  };
  return (
    <>
      <div className="draft-grid">
        {team("ally", `우리 팀${d.side ? ` · ${d.side}` : ""}`)}
        {team("enemy", "상대 팀")}
      </div>
      {d.my_pick && (
        <div style={{ marginTop: 16 }}>
          <div className="card-label">왜 {d.my_pick.champion}였을까</div>
          <Why text={d.my_pick.reason} source={d.my_pick.source} quote={d.my_pick.quote} />
        </div>
      )}
      <FrameStrip frames={d.frames} />
    </>
  );
}

/* ---------------- 턴 ---------------- */
const VERDICT_BADGE: Record<Turn["verdict"], string> = { 이득: "badge-blue", 교환: "badge-grey", 손해: "badge-red" };
const PLAN_BADGE: Record<Turn["followed_plan"], [string, string]> = {
  yes: ["플랜대로", "badge-green"], partial: ["일부 변경", "badge-orange"], no: ["플랜 이탈", "badge-orange"],
};

function TurnsView({ a, selected, onSelect }: { a: Analysis; selected: string | null; onSelect: (id: string) => void }) {
  const ally = a.turns?.ally ?? [];
  const enemy = a.turns?.enemy ?? [];
  if (ally.length === 0) return <p className="small">턴 정보가 없어요.</p>;
  const total = Math.max(secs(a.length || "0:00"), ...ally.map((t) => secs(t.to)), ...enemy.map((t) => secs(t.to)));

  return (
    <div>
      <Legend />
      <Timeline ally={ally} enemy={enemy} total={total} selected={selected} onSelect={onSelect} />
      <p className="caption" style={{ marginTop: 8 }}>막대에 마우스를 올리면 행동이, 누르면 그 턴 설명이 나와요. 흐린 막대는 캠프 타이머나 킬 로그로 추론한 상대 위치예요.</p>
      {a.turns.pattern && (
        <div className="card card-tight" style={{ marginTop: 24 }}>
          <div className="card-label">이 정글러가 턴을 쓰는 방식</div>
          {a.turns.pattern}
        </div>
      )}

      <section className="section">
        {ally.map((t) => <TurnCard key={t.id} t={t} on={selected === t.id} reviews={reviewsFor(a, t.id)} />)}
      </section>
    </div>
  );
}

function TurnCard({ t, on, reviews }: { t: Turn; on: boolean; reviews: ReviewComment[] }) {
  const { play, has, offset } = useClips();
  const canPlay = has("turns", t.id);
  const off = offset("turns", t.id);
  const st = t.start_state ?? {};
  const state = [st.level != null && `${st.level}레벨`, st.gold != null && `${st.gold}골드`, st.cs != null && `CS ${st.cs}`].filter(Boolean).join(" · ");
  const plan = PLAN_BADGE[t.followed_plan];
  return (
    <article id={t.id} className={`turn-card ${on ? "on" : ""}`}>
      <div className="turn-head">
        <span className="turn-id">{t.id.toUpperCase()}</span>
        <span className="time">{t.from} – {t.to}</span>
        <span className="caption">{t.end}으로 끝</span>
        <PlayButton group="turns" id={t.id} />
        <span style={{ marginLeft: "auto" }} className="row">
          {plan && <span className={`badge ${plan[1]}`}>{plan[0]}</span>}
          <span className={`badge ${VERDICT_BADGE[t.verdict] ?? "badge-grey"}`}>{t.verdict}</span>
        </span>
      </div>
      <TurnBar actions={t.actions} to={t.to} />

      <dl className="kv" style={{ marginTop: 16 }}>
        <dt>시작 상태</dt>
        <dd>
          {state && <div>{state}</div>}
          {st.lanes && <div>{st.lanes}</div>}
          {st.next_objective && <div className="small">다음 오브젝트: {st.next_objective}</div>}
          {st.enemy_jungler && <div className="small">상대 정글: {st.enemy_jungler}</div>}
        </dd>
        <dt>의도</dt><dd><Why text={t.intent} source={t.source} quote={t.quote} /></dd>
        {t.deviation && (<><dt>바뀐 이유</dt><dd>{t.deviation}</dd></>)}
      </dl>

      <ul className="actions">
        {t.actions.map((x, i) => (
          <li key={i}>
            {canPlay && off != null ? (
              <button className="at at-play" title="이 장면부터 영상 보기" onClick={() => play("turns", t.id, off + secs(x.t) - 2)}>{x.t}</button>
            ) : <span className="at">{x.t}</span>}
            <i className={`sw sw-${groupOf(x.kind)}`} />
            <span>{x.label}{x.where && x.where !== x.label ? <span className="ar"> · {x.where}</span> : null}{x.result && <div className="ar">{x.result}</div>}{x.why && <div className="why">{x.why}</div>}</span>
          </li>
        ))}
      </ul>

      {t.decisions && t.decisions.length > 0 && (
        <div className="decisions">
          <div className="card-label">판단 포인트 {t.decisions.length}</div>
          {t.decisions.map((d, i) => <DecisionCard key={i} d={d} turnId={t.id} />)}
        </div>
      )}

      <div className="gl">
        <div><b>얻은 것</b>{t.gained?.length ? t.gained.join(", ") : "없음"}</div>
        <div><b>잃은 것</b>{t.lost?.length ? t.lost.join(", ") : "없음"}</div>
      </div>
      {t.exchange && <div className="rule-box"><div className="when">같은 시간 상대 정글</div><div className="then" style={{ fontWeight: 500 }}>{t.exchange}</div></div>}
      <ReviewNotes items={reviews} />
      <FrameStrip frames={t.frames} />
    </article>
  );
}

/* ---------------- 운영 ---------------- */
const DECISION_BADGE: Record<string, string> = { 싸움: "badge-orange", 교환: "badge-blue", 포기: "badge-grey", 무혈: "badge-green" };

function OpsView({ a }: { a: Analysis }) {
  const o = a.operations;
  if (!o) return <p className="small">운영 정보가 없어요.</p>;
  return (
    <div>
      {o.plan_vs_result && (
        <div className="card">
          <div className="card-label">플랜은 어떻게 흘러갔나</div>
          {o.plan_vs_result}
        </div>
      )}

      {o.turning_points?.length > 0 && (
        <section className="section">
          <h2 className="section-title">변곡점</h2>
          {o.turning_points.map((p, i) => (
            <article key={i} id={`p${i + 1}`} className="scene" style={{ scrollMarginTop: 130 }}>
              <div className="scene-head"><span className="time">{p.ingame}</span><PlayButton group="tps" id={`p${i + 1}`} /><span className="caption" style={{ marginLeft: "auto" }}>VOD {p.vod}</span></div>
              <h3 className="t3">{p.title}</h3>
              <dl className="kv" style={{ marginTop: 16 }}>
                <dt>무슨 일</dt><dd>{p.what}</dd>
                <dt>왜 결정적</dt><dd>{p.why_decisive}</dd>
              </dl>
              {p.better && <div className="rule-box"><div className="when">이렇게 했다면</div><div className="then">{p.better}</div></div>}
              <FrameStrip frames={p.frames} />
            </article>
          ))}
        </section>
      )}

      {o.objective_cycles?.length > 0 && (
        <section className="section">
          <h2 className="section-title">오브젝트</h2>
          {o.objective_cycles.map((c, i) => (
            <div key={i} id={`o${i + 1}`} className="obj-row">
              <div className="obj-time">{c.spawn}<small>{c.objective}</small></div>
              <div>
                <div className="row" style={{ marginBottom: 8 }}>
                  <span className={`badge ${DECISION_BADGE[c.decision] ?? "badge-grey"}`}>{c.decision}</span>
                  {c.taken_by === "ally" && <span className="badge badge-blue">우리 획득</span>}
                  {c.taken_by === "enemy" && <span className="badge badge-red">상대 획득</span>}
                  <SourceBadge source={c.source} />
                </div>
                <dl className="kv" style={{ fontSize: 15 }}>
                  <dt>준비</dt><dd>{c.prep_from && <span className="caption">{c.prep_from}부터 · </span>}{c.prep}</dd>
                  {c.trade && (<><dt>대신</dt><dd>{c.trade}</dd></>)}
                  <dt>결과</dt><dd>{c.result}</dd>
                </dl>
                <FrameStrip frames={c.frames} />
              </div>
            </div>
          ))}
        </section>
      )}

      {o.phases?.length > 0 && (
        <section className="section">
          <h2 className="section-title">단계별 운영</h2>
          <div className="stack">
            {o.phases.map((ph) => (
              <div key={ph.phase} className="card card-tight">
                <div className="row"><b>{ph.phase}</b><span className="caption">{ph.range}</span></div>
                <p style={{ margin: "8px 0 0" }}>{ph.summary}</p>
                {ph.points?.length > 0 && <ul className="bullets">{ph.points.map((x, i) => <li key={i}>{x}</li>)}</ul>}
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

/* ---------------- 교전 ---------------- */
function FightsView({ a, concepts }: { a: Analysis; concepts: Map<string, Concept> }) {
  const fights = a.fights ?? [];
  if (fights.length === 0) return <p className="small">뜯어본 교전이 없어요.</p>;
  return (
    <div>
      {fights.map((s) => {
        const i = s.rule?.indexOf("→") ?? -1;
        return (
          <article key={s.id} className="scene" id={s.id} style={{ scrollMarginTop: 130 }}>
            <div className="scene-head">
              <span className="time">{s.ingame}</span>
              <PlayButton group="fights" id={s.id} />
              <span className="caption" style={{ marginLeft: "auto" }}>VOD {s.vod}</span>
            </div>
            <h3 className="t3">{s.title}</h3>
            <FrameStrip frames={s.frames} />
            <dl className="kv">
              <dt>상황</dt><dd>{s.situation}</dd>
              <dt>선택</dt><dd style={{ fontWeight: 600, color: "var(--grey-900)" }}>{s.choice}</dd>
              <dt>이유</dt><dd><Why text={s.reason} source={s.source} quote={s.quote} /></dd>
            </dl>
            {s.fight && (
              <div className="fight">
                <div className="card-label">교전 뜯어보기</div>
                <dl className="kv">
                  <dt>들어가기 전</dt><dd>{s.fight.before}</dd>
                  <dt>시작</dt><dd>{s.fight.start}</dd>
                  <dt>진행</dt><dd>{s.fight.flow}</dd>
                  <dt>승부처</dt><dd style={{ fontWeight: 600, color: "var(--grey-900)" }}>{s.fight.decisive}</dd>
                </dl>
                {s.fight.uncertain?.length > 0 && <p className="caption" style={{ marginTop: 12 }}>정지 화면이라 확실하지 않아요: {s.fight.uncertain.join(", ")}</p>}
              </div>
            )}
            {s.rule && (
              <div className="rule-box">
                {i >= 0 ? (<><div className="when">{s.rule.slice(0, i).trim()}</div><div className="then">→ {s.rule.slice(i + 1).trim()}</div></>) : <div className="then">{s.rule}</div>}
              </div>
            )}
            <Background items={s.background} />
            <ReviewNotes items={reviewsFor(a, s.id)} />
            {s.concepts?.length > 0 && (
              <div className="row" style={{ marginTop: 12 }}>
                {s.concepts.map((id) => <Link key={id} to={`/concepts/${id}`} className="chip">{concepts.get(id)?.name ?? id}</Link>)}
              </div>
            )}
          </article>
        );
      })}
    </div>
  );
}

/* ---------------- 리플레이 피드백 ---------------- */
const KIND_BADGE: Record<string, string> = { 실수: "badge-red", "잘한 점": "badge-blue", 대안: "badge-orange", 설명: "badge-grey" };

function refLabel(id: string) {
  if (id.startsWith("t")) return `${id.toUpperCase()} 턴 보기`;
  if (id.startsWith("f")) return "교전 보기";
  if (id.startsWith("p")) return "변곡점 보기";
  if (id.startsWith("o")) return "오브젝트 보기";
  return id;
}

/** 턴 카드, 교전 안에 붙는 "리플레이에서 한 말" */
function ReviewNotes({ items }: { items: ReviewComment[] }) {
  if (!items.length) return null;
  return (
    <div className="review-notes">
      <div className="card-label">리플레이에서 스트리머가 한 말</div>
      {items.map((c) => (
        <Link key={c.id} to={{ hash: c.id }} className="review-note">
          <span className={`badge ${KIND_BADGE[c.kind] ?? "badge-grey"}`}>{c.kind}</span>
          <span>“{c.said}”</span>
        </Link>
      ))}
    </div>
  );
}

function ReviewView({ a }: { a: Analysis }) {
  const r = a.review;
  if (!r?.available) return <p className="small">이 판은 리플레이 피드백이 없어요.</p>;
  const comments = [...(r.comments ?? [])].sort((x, y) => secs(x.ingame ?? "99:59") - secs(y.ingame ?? "99:59"));
  const counts = (["실수", "대안", "잘한 점", "설명"] as const).map((k) => [k, comments.filter((c) => c.kind === k).length] as const).filter(([, n]) => n);
  return (
    <div>
      <div className="card">
        <div className="card-label">경기 뒤 리플레이를 보며 짚은 것</div>
        {r.summary && <div style={{ fontWeight: 600, fontSize: 17 }}>{r.summary}</div>}
        <div className="row" style={{ marginTop: 12 }}>
          {counts.map(([k, n]) => <span key={k} className={`badge ${KIND_BADGE[k]}`}>{k} {n}</span>)}
          {r.segments?.length ? <span className="caption">VOD {r.segments.map((s) => `${s.from}~${s.to}`).join(", ")}</span> : null}
        </div>
        <p className="caption" style={{ marginTop: 12, marginBottom: 0 }}>결과를 알고 돌아보며 한 말이라, 경기 중에 한 판단과 다를 수 있어요.</p>
      </div>
      <section className="section">
        {comments.map((c) => (
          <article key={c.id} id={c.id} className="scene" style={{ scrollMarginTop: 130 }}>
            <div className="scene-head">
              <span className="time">{c.ingame ?? "시각 모름"}</span>
              <span className={`badge ${KIND_BADGE[c.kind] ?? "badge-grey"}`}>{c.kind}</span>
              <PlayButton group="reviews" id={c.id} label="리플레이 보기" />
              <span className="caption" style={{ marginLeft: "auto" }}>VOD {c.vod}</span>
            </div>
            <div className="quote">“{c.said}”</div>
            <div className="rule-box"><div className="then">{c.point}</div></div>
            {c.refs?.length > 0 && (
              <div className="row" style={{ marginTop: 12 }}>
                {c.refs.map((id) => <Link key={id} to={{ hash: id }} className="chip">{refLabel(id)}</Link>)}
              </div>
            )}
            <FrameStrip frames={c.frames} />
          </article>
        ))}
      </section>
    </div>
  );
}

/* ---------------- 판단 포인트, 배경지식 ---------------- */
/** 이 판단을 이해하는 데 필요한 챔피언, 메커니즘 지식 */
function Background({ items }: { items?: string[] }) {
  if (!items?.length) return null;
  return (
    <div className="bg-box">
      <div className="bg-label">알아야 할 것</div>
      <ul>{items.map((x, i) => <li key={i}>{x}</li>)}</ul>
    </div>
  );
}

function DecisionCard({ d, turnId }: { d: Decision; turnId: string }) {
  const { play, has, offset } = useClips();
  const off = offset("turns", turnId);
  return (
    <div className="decision">
      <div className="decision-head">
        {has("turns", turnId) && off != null
          ? <button className="at at-play" onClick={() => play("turns", turnId, off + secs(d.t) - 5)} title="이 장면부터 영상 보기">{d.t}</button>
          : <span className="at">{d.t}</span>}
        <b>{d.question}</b>
      </div>
      <p className="decision-situation">{d.situation}</p>
      <ul className="options">
        {d.options.map((o, i) => (
          <li key={i} className={o.chosen ? "chosen" : ""}>
            <span className="opt-mark">{o.chosen ? "선택" : "대안"}</span>
            <span><b>{o.label}</b> {o.why}</span>
          </li>
        ))}
      </ul>
      <dl className="kv" style={{ marginTop: 12 }}>
        <dt>이유</dt><dd><Why text={d.why} source={d.source} quote={d.quote} /></dd>
        <dt>결과</dt><dd>{d.result}</dd>
      </dl>
      <Background items={d.background} />
      {d.frames && d.frames.length > 0 && <FrameStrip frames={d.frames} />}
    </div>
  );
}

function NextGoalButton({ text, rule }: { text: string; rule?: string | null }) {
  const [done, setDone] = useState(false);
  return (
    <button className="btn btn-primary btn-sm" disabled={done} onClick={async () => { await api.setGoal(text, rule); setDone(true); }}>
      {done ? "다음 판 목표로 정했어요" : "다음 판 목표로 정하기"}
    </button>
  );
}
