import { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, CATEGORIES, gamePath, media, TIERS, type Profile, type TrainItem, type TrainReveal } from "../api";
import { BottomCTA, Dots, ErrorView, Loading, PageHead, SourceBadge, usePoll } from "../ui";
import { hmsOf } from "./game/time";

const LIMIT = 15; // 답하는 시간(초). 고수의 판단은 계산보다 패턴 인식이라 시간 제한을 둔다
const CONF = [
  { v: 2, label: "확실해요" },
  { v: 1, label: "아마도" },
  { v: 0, label: "찍었어요" },
];

function lsGet(k: string) { try { return window.localStorage.getItem(k); } catch { return null; } }
function lsSet(k: string, v: string) { try { window.localStorage.setItem(k, v); } catch { /* 없어도 동작 */ } }

/* ================= 훈련 홈 ================= */
export default function Train() {
  const { data, error, reload } = usePoll(api.trainOverview, [], () => false);
  const { data: me, reload: reloadMe } = usePoll(api.me, [], () => false);
  const [session, setSession] = useState<TrainItem[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [count, setCount] = useState(10);
  const [source, setSource] = useState("all");
  const [cat, setCat] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [params, setParams] = useSearchParams();

  // ?start=10 으로 바로 시작 (알림, 다른 화면의 "지금 훈련" 링크). &game=<판>이면 그 판의 판단만 (복기 시간)
  useEffect(() => {
    const n = Number(params.get("start"));
    if (!n) return;
    setParams({}, { replace: true });
    void api.trainSession(n, params.get("category"), params.get("source") ?? "all", params.get("game")).then(({ items }) => items.length && setSession(items));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (error) return <ErrorView message={error} />;
  if (!data || !me) return <Loading />;

  if (session) {
    return <Session items={session} onExit={() => { setSession(null); reload(); }} />;
  }

  const start = async () => {
    setLoading(true);
    setErr(null);
    try {
      const { items } = await api.trainSession(count, cat, source);
      if (items.length === 0) setErr("지금 풀 문제가 없어요. 조건을 바꾸거나 판을 더 분석해 주세요.");
      else setSession(items);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const weak = Object.entries(data.stats)
    .filter(([, s]) => s.n >= 3)
    .sort((a, b) => a[1].rate - b[1].rate)
    .slice(0, 3);
  const cats = CATEGORIES.filter((c) => data.categories[c]);
  const todo = data.due + Math.min(data.new, 10);

  if (data.total === 0) {
    return (
      <div className="empty">
        <div className="empty-icon">🎯</div>
        <h1 className="t1">{"아직 훈련할\n장면이 없어요"}</h1>
        <p className="sub">{"프로 영상이나 내 게임을 분석하면\n판단 포인트가 훈련 문제로 쌓여요"}</p>
        <div className="row" style={{ justifyContent: "center", marginTop: 24 }}>
          <Link to="/vods" className="btn btn-primary">프로 영상 보러 가기</Link>
          <Link to="/mine" className="btn btn-secondary">내 게임 녹화 연결하기</Link>
        </div>
      </div>
    );
  }

  return (
    <div className="layout">
      <div>
        <PageHead
          title={data.due > 0 ? `오늘 다시 볼 장면\n${data.due}개가 있어요` : "오늘의 판단 훈련"}
          sub="영상이 판단 직전에 멈춰요. 15초 안에 고르고, 바로 정답과 이유를 봐요."
        />
        {!me.tier && <ProfileCard me={me} onSaved={reloadMe} />}

        <div className="stats">
          <div className="stat"><div className="stat-num">{data.due}</div><div className="stat-label">다시 볼 장면</div></div>
          <div className="stat"><div className="stat-num">{data.new}</div><div className="stat-label">새 장면</div></div>
          <div className="stat"><div className="stat-num">{data.streak}일</div><div className="stat-label">연속 훈련</div></div>
        </div>

        <section className="section">
          <h2 className="section-title">어떤 장면으로 할까요?</h2>
          <div className="row" style={{ marginBottom: 12 }}>
            {[["all", "전체"], ["pro", "프로 영상"], ["mine", `내 게임${data.own_total ? ` ${data.own_total}` : ""}`]].map(([k, l]) => (
              <button key={k} className={`chip ${source === k ? "on" : ""}`} onClick={() => setSource(k)}>{l}</button>
            ))}
          </div>
          <div className="row">
            <button className={`chip ${!cat ? "on" : ""}`} onClick={() => setCat(null)}>모든 유형 섞기</button>
            {cats.map((c) => (
              <button key={c} className={`chip ${cat === c ? "on" : ""}`} onClick={() => setCat(c)}>
                {c} <span className="chip-n">{data.categories[c].total}</span>
              </button>
            ))}
          </div>
        </section>
        <section className="section">
          <h2 className="section-title">몇 문제 풀까요?</h2>
          <div className="row">
            {[5, 10, 20].map((n) => <button key={n} className={`chip ${count === n ? "on" : ""}`} onClick={() => setCount(n)}>{n}문제</button>)}
          </div>
        </section>
        {err && <p className="field-error">{err}</p>}
        <BottomCTA>
          <button className="btn btn-primary btn-lg" onClick={start} disabled={loading} aria-busy={loading}>
            {loading ? <Dots /> : todo > 0 ? "훈련 시작" : "새 장면으로 훈련"}
          </button>
        </BottomCTA>
        <p className="caption" style={{ marginTop: 24 }}>
          서술형 문제는 <Link to="/review">서술형 복습</Link>에서 풀 수 있어요.
        </p>
      </div>

      <aside className="aside">
        <div className="card card-tight">
          <div className="card-label">오늘</div>
          <div style={{ fontSize: 22, fontWeight: 700 }}>{data.today.n}문제 <span className="small">정답 {data.today.n ? Math.round((data.today.ok / data.today.n) * 100) : 0}%</span></div>
        </div>
        <div className="card card-tight" style={{ marginTop: 12 }}>
          <div className="card-label">약한 판단 유형 (최근 30일)</div>
          {weak.length === 0 ? (
            <p className="small" style={{ margin: 0 }}>유형마다 3문제 이상 풀면 약점이 보여요.</p>
          ) : (
            weak.map(([c, s]) => (
              <button key={c} className="weak-row" onClick={() => setCat(c)}>
                <span>{c}</span>
                <span className="bar"><i style={{ width: `${s.rate * 100}%` }} /></span>
                <b>{Math.round(s.rate * 100)}%</b>
              </button>
            ))
          )}
        </div>
        {me.tier && (
          <div className="card card-tight" style={{ marginTop: 12 }}>
            <div className="card-label">내 프로필</div>
            <div style={{ fontWeight: 600 }}>{me.tier}{me.division ? ` ${me.division}` : ""} · {me.role ?? "정글"}</div>
            <div className="small">주 {me.weekly_games ?? "?"}판{me.goal_tier ? ` · 목표 ${me.goal_tier}` : ""}</div>
          </div>
        )}
      </aside>
    </div>
  );
}

/* ================= 프로필 (처음 한 번) ================= */
function ProfileCard({ me, onSaved }: { me: Profile; onSaved: () => void }) {
  const [tier, setTier] = useState(me.tier ?? "");
  const [goal, setGoal] = useState(me.goal_tier ?? "");
  const [weekly, setWeekly] = useState(me.weekly_games ?? 5);
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    try { await api.saveMe({ tier, goal_tier: goal || null, weekly_games: weekly, role: "정글" }); onSaved(); } finally { setBusy(false); }
  };
  return (
    <div className="card card-blue" style={{ marginBottom: 32 }}>
      <div className="card-label">처음이시네요</div>
      <div style={{ fontWeight: 700, fontSize: 18, marginBottom: 12 }}>지금 티어를 알려 주시면 맞는 장면부터 내 드려요</div>
      <label className="field-label">지금 티어</label>
      <div className="row" style={{ marginBottom: 12 }}>
        {TIERS.map((t) => <button key={t} className={`chip ${tier === t ? "on" : ""}`} onClick={() => setTier(t)}>{t}</button>)}
      </div>
      <label className="field-label">목표 티어</label>
      <div className="row" style={{ marginBottom: 12 }}>
        {TIERS.slice(Math.max(0, TIERS.indexOf(tier))).map((t) => <button key={t} className={`chip ${goal === t ? "on" : ""}`} onClick={() => setGoal(t)}>{t}</button>)}
      </div>
      <label className="field-label">일주일에 몇 판 하세요?</label>
      <div className="row" style={{ marginBottom: 16 }}>
        {[3, 5, 10, 20].map((n) => <button key={n} className={`chip ${weekly === n ? "on" : ""}`} onClick={() => setWeekly(n)}>{n}판{n === 20 ? " 이상" : ""}</button>)}
      </div>
      <button className="btn btn-primary" disabled={!tier || busy} onClick={save}>저장</button>
    </div>
  );
}

/* ================= 훈련 세션 ================= */
type Phase = "lead" | "question" | "reveal";

function Session({ items, onExit }: { items: TrainItem[]; onExit: () => void }) {
  const [i, setI] = useState(0);
  const [results, setResults] = useState<{ item: TrainItem; r: TrainReveal; conf: number }[]>([]);
  if (i >= items.length) return <Summary results={results} onExit={onExit} />;
  const item = items[i];
  return (
    <>
      <div className="progress" style={{ marginBottom: 20 }}><div style={{ width: `${(i / items.length) * 100}%` }} /></div>
      <div className="eyebrow">
        <span>{i + 1} / {items.length}</span><span>·</span><span>{item.category}</span>
        {item.own && <span className="badge badge-orange">내 게임</span>}
        <button className="chip" style={{ marginLeft: "auto", padding: "4px 10px", fontSize: 13 }} onClick={onExit}>그만하기</button>
      </div>
      <Question key={item.id} item={item} onDone={(r, conf) => setResults((x) => [...x, { item, r, conf }])} onNext={() => { setI(i + 1); window.scrollTo(0, 0); }} />
    </>
  );
}

function Question({ item, onDone, onNext }: { item: TrainItem; onDone: (r: TrainReveal, conf: number) => void; onNext: () => void }) {
  const [phase, setPhase] = useState<Phase>("lead");
  const [sel, setSel] = useState<number | null>(null);
  const [reveal, setReveal] = useState<TrainReveal | null>(null);
  const [conf, setConf] = useState<number | null>(null);
  const [timed, setTimed] = useState(() => lsGet("train-timer") !== "off");
  const [left, setLeft] = useState(LIMIT);
  const [busy, setBusy] = useState(false);
  const askedAt = useRef(0);
  const sceneRef = useRef<SceneHandle>(null);

  const submit = useCallback(async (choice: number | null, confidence: number) => {
    if (busy || reveal) return;
    setBusy(true);
    setConf(confidence);
    try {
      const r = await api.trainAnswer(item.id, choice, confidence, Math.round(performance.now() - askedAt.current));
      setReveal(r);
      setPhase("reveal");
      onDone(r, confidence);
    } finally {
      setBusy(false);
    }
  }, [busy, reveal, item.id, onDone]);

  const ask = useCallback(() => {
    setPhase((p) => (p === "lead" ? "question" : p));
    askedAt.current = performance.now();
  }, []);

  // 제한 시간
  useEffect(() => {
    if (phase !== "question" || !timed) return;
    setLeft(LIMIT);
    const id = window.setInterval(() => setLeft((s) => s - 1), 1000);
    return () => window.clearInterval(id);
  }, [phase, timed]);
  useEffect(() => {
    if (phase === "question" && timed && left <= 0) void submit(sel, 0);
  }, [left, phase, timed, sel, submit]);

  // 키보드: 1~3 선택지, Q/W/E 확신도, Enter 다음
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLTextAreaElement || e.target instanceof HTMLInputElement) return;
      if (phase === "question") {
        const n = Number(e.key);
        if (n >= 1 && n <= item.options.length) setSel(item.options[n - 1].key);
        const c = { q: 2, w: 1, e: 0 }[e.key.toLowerCase()];
        if (c !== undefined && sel !== null) void submit(sel, c);
      } else if (phase === "reveal" && e.key === "Enter") onNext();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [phase, item.options, sel, submit, onNext]);

  const opt = (key: number) => reveal?.options.find((o) => o.key === key);
  const streamerPick = reveal?.options.find((o) => o.chosen);
  const who = item.own ? "내가" : (item.streamer ?? "스트리머");

  return (
    <div className="quiz-layout">
      <div className="quiz-media">
        <Scene ref={sceneRef} item={item} phase={phase} onPaused={ask} />
        <div className="scene-meta">
          <b>{item.champion}</b>{item.enemy_jungler ? ` vs ${item.enemy_jungler}` : ""} · 인게임 {item.ingame}
          {item.context && item.context !== "솔로랭크" && <span className="badge badge-grey" style={{ marginLeft: 6 }}>{item.context}</span>}
        </div>
      </div>

      <div>
        <h1 className="t2" style={{ marginBottom: 12 }}>{item.question}</h1>
        <p className="situation">{item.situation}</p>

        {phase === "lead" && (
          <div className="lead-wait">
            영상이 판단 직전까지 재생되고 있어요 <Dots />
            <button className="btn btn-ghost btn-sm" onClick={() => { sceneRef.current?.skip(); ask(); }}>바로 풀기</button>
          </div>
        )}

        {phase !== "lead" && (
          <>
            {phase === "question" && timed && (
              <div className="timer" aria-live="polite">
                <div className="timer-bar"><i style={{ width: `${(left / LIMIT) * 100}%` }} /></div>
                <span>{Math.max(0, left)}초</span>
              </div>
            )}
            <div className="train-options" role="radiogroup">
              {item.options.map((o, idx) => {
                const r = opt(o.key);
                const cls = reveal
                  ? [o.key === reveal.best ? "best" : "", sel === o.key && o.key !== reveal.best ? "wrong" : ""].join(" ")
                  : sel === o.key ? "on" : "";
                return (
                  <button key={o.key} role="radio" aria-checked={sel === o.key} className={`train-opt ${cls}`}
                    disabled={!!reveal} onClick={() => setSel(o.key)}>
                    <span className="opt-n">{idx + 1}</span>
                    <span className="opt-body">
                      <b>{o.label}</b>
                      {reveal && (
                        <span className="opt-tags">
                          {o.key === reveal.best && <span className="badge badge-blue">더 나은 선택</span>}
                          {r?.chosen && <span className="badge badge-grey">{who} 고름</span>}
                          {sel === o.key && <span className="badge badge-orange">내 답</span>}
                        </span>
                      )}
                      {reveal && r?.why && <span className="opt-why">{r.why}</span>}
                    </span>
                  </button>
                );
              })}
            </div>

            {phase === "question" && (
              <div className="conf">
                <div className="small" style={{ marginBottom: 8 }}>{sel === null ? "선택지를 고르면 얼마나 확신하는지 물어볼게요" : "얼마나 확신하세요?"}</div>
                <div className="conf-row">
                  {CONF.map((c, k) => (
                    <button key={c.v} className="btn btn-secondary" disabled={sel === null || busy} onClick={() => void submit(sel, c.v)}>
                      {c.label}<small>{"QWE"[k]}</small>
                    </button>
                  ))}
                </div>
                <label className="caption timer-toggle">
                  <input type="checkbox" checked={timed} onChange={(e) => { setTimed(e.target.checked); lsSet("train-timer", e.target.checked ? "on" : "off"); }} /> 15초 제한
                </label>
              </div>
            )}

            {reveal && (
              <div className="reveal">
                <div className={`reveal-head ${reveal.correct ? "ok" : "no"}`}>
                  {reveal.correct ? "맞혔어요" : sel === null ? "시간이 지났어요" : "아쉬워요"}
                  <span>
                    {!reveal.correct && conf === 2 ? "확신했던 문제라 내일 먼저 다시 나와요" : `다음 복습 ${reveal.next.interval_days <= 1 ? "내일" : `${Math.round(reveal.next.interval_days)}일 뒤`}`}
                  </span>
                </div>
                {streamerPick && streamerPick.key !== reveal.best && (
                  <p className="small" style={{ marginTop: 12 }}>
                    실제로는 <b>{streamerPick.label}</b>을(를) 골랐지만, 결과와 피드백을 보면 <b>{opt(reveal.best)?.label}</b>이(가) 더 나았어요.
                  </p>
                )}
                <dl className="kv" style={{ marginTop: 16 }}>
                  {reveal.why && (<><dt>이유</dt><dd>{reveal.why} {reveal.source && <SourceBadge source={reveal.source} />}{reveal.quote && <div className="quote">“{reveal.quote}”</div>}</dd></>)}
                  {reveal.result && (<><dt>결과</dt><dd>{reveal.result}</dd></>)}
                </dl>
                {reveal.background.length > 0 && (
                  <div className="bg-box"><div className="bg-label">알아야 할 것</div><ul>{reveal.background.map((x, k) => <li key={k}>{x}</li>)}</ul></div>
                )}
                <div className="row" style={{ marginTop: 20 }}>
                  {item.video && <button className="btn btn-ghost" onClick={() => sceneRef.current?.playAfter(reveal.after)}>▶ 이어서 보기</button>}
                  <Link className="btn btn-ghost" to={gamePath(item.game_ref, item.turn)} target="_blank">이 턴 분석 보기</Link>
                  <button className="btn btn-primary" style={{ marginLeft: "auto" }} onClick={onNext}>다음 <small style={{ opacity: .7 }}>Enter</small></button>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

/* ================= 장면: 판단 직전까지 재생하고 멈춤 ================= */
interface SceneHandle { skip: () => void; playAfter: (sec: number) => void }


const Scene = forwardRef<SceneHandle, { item: TrainItem; phase: Phase; onPaused: () => void }>(function Scene({ item, phase, onPaused }, ref) {
  const v = useRef<HTMLVideoElement>(null);
  const [muted, setMuted] = useState(true);
  const [now, setNow] = useState<number | null>(null);
  const [stopAt, setStopAt] = useState<number | null>(null);
  const [failed, setFailed] = useState(!item.video);
  const can = item.video && item.base != null && item.at != null && !failed;

  useEffect(() => {
    if (!can) { onPaused(); return; }
    const el = v.current!;
    const go = () => {
      el.currentTime = Math.max(0, item.at! - item.lead - item.base!);
      setStopAt(item.at!);
      void el.play().catch(() => { setFailed(true); onPaused(); });
    };
    if (el.readyState >= 1) go(); else el.addEventListener("loadedmetadata", go, { once: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item.id]);

  useImperativeHandle(ref, () => ({
    skip: () => {
      const el = v.current;
      if (!el || !can) return;
      el.pause();
      el.currentTime = item.at! - item.base!;
      setStopAt(null);
    },
    playAfter: (sec: number) => {
      const el = v.current;
      if (!el || !can) return;
      el.currentTime = item.at! - item.base!;
      el.muted = false;
      setMuted(false);
      setStopAt(item.at! + sec);
      void el.play();
    },
  }), [can, item.at, item.base]);

  const onTime = () => {
    const el = v.current!;
    const t = item.base! + el.currentTime;
    setNow(t);
    if (stopAt != null && t >= stopAt) {
      el.pause();
      setStopAt(null);
      if (phase === "lead") onPaused();
    }
  };

  const ingame = now != null && item.ingame_offset != null ? now - item.ingame_offset : null;

  if (!can) {
    return item.image
      ? <img className="quiz-img" src={media(item.image)} alt="판단 직전 장면" />
      : <div className="scene-empty">이 장면은 영상이 없어요. 상황 설명을 보고 판단해 주세요.</div>;
  }
  return (
    <div className="scene">
      <video ref={v} src={media(item.video!)} muted={muted} playsInline preload="auto" onTimeUpdate={onTime}
        controls={phase === "reveal"} onError={() => { setFailed(true); onPaused(); }} />
      {ingame != null && ingame >= 0 && <span className="scene-clock">{hmsOf(ingame)}</span>}
      {phase === "question" && <span className="scene-paused">판단 직전에서 멈췄어요</span>}
      {phase !== "reveal" && (
        <div className="scene-tools">
          <button onClick={() => { const el = v.current!; el.currentTime = Math.max(0, item.at! - item.lead - item.base!); setStopAt(item.at!); void el.play(); }}>↺ 다시 보기</button>
          <button onClick={() => setMuted((m) => !m)}>{muted ? "🔇 소리 켜기" : "🔊 소리 끄기"}</button>
        </div>
      )}
    </div>
  );
});

/* ================= 결과 ================= */
function Summary({ results, onExit }: { results: { item: TrainItem; r: TrainReveal; conf: number }[]; onExit: () => void }) {
  const ok = results.filter((x) => x.r.correct).length;
  const sureWrong = results.filter((x) => !x.r.correct && x.conf === 2);
  const byCat = useMemo(() => {
    const m = new Map<string, { n: number; ok: number }>();
    for (const x of results) {
      const c = m.get(x.item.category) ?? { n: 0, ok: 0 };
      c.n += 1; if (x.r.correct) c.ok += 1;
      m.set(x.item.category, c);
    }
    return [...m.entries()].sort((a, b) => a[1].ok / a[1].n - b[1].ok / b[1].n);
  }, [results]);
  return (
    <div className="narrow-wrap">
      <div className="empty" style={{ paddingBottom: 24 }}>
        <div className="empty-icon">{ok === results.length ? "🎉" : "💪"}</div>
        <h1 className="t1">{`${results.length}문제 중 ${ok}문제\n맞혔어요`}</h1>
        <p className="sub">{sureWrong.length ? `확신했는데 틀린 ${sureWrong.length}문제는 내일 가장 먼저 다시 나와요.` : "틀린 문제는 내일 다시 나와요."}</p>
      </div>
      <div className="card card-tight">
        <div className="card-label">유형별</div>
        {byCat.map(([c, s]) => (
          <div key={c} className="weak-row" style={{ cursor: "default" }}>
            <span>{c}</span><span className="bar"><i style={{ width: `${(s.ok / s.n) * 100}%` }} /></span><b>{s.ok}/{s.n}</b>
          </div>
        ))}
      </div>
      {sureWrong.length > 0 && (
        <section className="section">
          <h2 className="section-title">확신했는데 틀린 장면</h2>
          <div className="list">
            {sureWrong.map((x) => (
              <Link key={x.item.id} to={gamePath(x.item.game_ref, x.item.turn)} className="list-row">
                <div className="list-body">
                  <div className="list-title">{x.item.question}</div>
                  <div className="list-desc">더 나은 선택: {x.r.options.find((o) => o.key === x.r.best)?.label}</div>
                </div>
                <span className="chev">›</span>
              </Link>
            ))}
          </div>
        </section>
      )}
      <BottomCTA><button className="btn btn-primary btn-lg" onClick={onExit}>확인</button></BottomCTA>
    </div>
  );
}
