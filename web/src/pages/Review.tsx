import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, gamePath, media, QUIZ_TYPES, type KB, type Quiz } from "../api";
import { BottomCTA, Dots, ErrorView, Loading, PageHead, useLightbox, usePoll } from "../ui";

const today = () => new Date().toISOString().slice(0, 10);

/** 안 푼 문제 → 틀린 문제 → 애매한 문제 → 오래전에 맞힌 문제 순 */
function order(kb: KB, quizzes: Quiz[]) {
  const rank = (q: Quiz) => {
    const log = kb.quiz_log[q.id] ?? [];
    const last = log[log.length - 1];
    if (!last) return [0, ""] as const;
    return [last.result === "X" ? 1 : last.result === "△" ? 2 : 3, last.date] as const;
  };
  return [...quizzes].sort((a, b) => {
    const [ra, da] = rank(a);
    const [rb, db] = rank(b);
    return ra - rb || da.localeCompare(db);
  });
}

export default function Review() {
  const [params] = useSearchParams();
  const concept = params.get("concept");
  const { data: kb, error, reload } = usePoll(api.kb, [], () => false);
  const [cat, setCat] = useState<string | null>(null);
  const [count, setCount] = useState(5);
  const [session, setSession] = useState<Quiz[] | null>(null);

  const pool = useMemo(() => {
    if (!kb) return [];
    return kb.quizzes.filter((q) => (!concept || q.concepts.includes(concept)) && (!cat || q.category === cat));
  }, [kb, cat, concept]);

  if (error) return <ErrorView message={error} />;
  if (!kb) return <Loading />;

  if (session) {
    return <Session quizzes={session} kb={kb} onExit={() => { setSession(null); reload(); }} />;
  }

  if (kb.quizzes.length === 0) {
    return (
      <div className="empty">
        <div className="empty-icon">✏️</div>
        <h1 className="t2">아직 문제가 없어요</h1>
        <p className="sub">{"판을 분석하면 실제 장면으로\n상황 판단 문제를 만들어요"}</p>
      </div>
    );
  }

  const logs = Object.values(kb.quiz_log).flat();
  const todayCount = logs.filter((l) => l.date === today()).length;
  const lastResults = kb.quizzes.map((q) => kb.quiz_log[q.id]?.at(-1)?.result).filter(Boolean);
  const rate = lastResults.length ? Math.round((lastResults.filter((r) => r === "O").length / lastResults.length) * 100) : null;
  const unseen = kb.quizzes.filter((q) => !kb.quiz_log[q.id]?.length).length;
  const wrong = kb.quizzes.filter((q) => kb.quiz_log[q.id]?.at(-1)?.result === "X").length;
  const cats = [...new Set(kb.quizzes.map((q) => q.category))];
  const conceptName = concept ? kb.concepts.find((c) => c.id === concept)?.name : null;

  return (
    <div className="narrow-wrap">
      <PageHead
        eyebrow={conceptName ? <><Link to={`/concepts/${concept}`}>‹ {conceptName}</Link></> : undefined}
        title={conceptName ? `${conceptName}\n복습하기` : "복습"}
        sub={unseen ? `아직 안 푼 문제가 ${unseen}개 있어요` : wrong ? `틀렸던 문제 ${wrong}개부터 다시 풀어요` : "실제 장면으로 판단력을 다져요"}
      />
      <div className="stats">
        <div className="stat"><div className="stat-num">{kb.quizzes.length}</div><div className="stat-label">전체 문제</div></div>
        <div className="stat"><div className="stat-num">{todayCount}</div><div className="stat-label">오늘 푼 문제</div></div>
        <div className="stat"><div className="stat-num">{rate === null ? "-" : `${rate}%`}</div><div className="stat-label">최근 정답률</div></div>
      </div>

      {!concept && cats.length > 1 && (
        <section className="section">
          <h2 className="section-title">어떤 문제를 풀까요?</h2>
          <div className="row">
            <button className={`chip ${!cat ? "on" : ""}`} onClick={() => setCat(null)}>전체</button>
            {cats.map((c) => <button key={c} className={`chip ${cat === c ? "on" : ""}`} onClick={() => setCat(c)}>{c}</button>)}
          </div>
        </section>
      )}
      <section className="section">
        <h2 className="section-title">몇 문제 풀까요?</h2>
        <div className="row">
          {[3, 5, 10].map((n) => <button key={n} className={`chip ${count === n ? "on" : ""}`} onClick={() => setCount(n)}>{n}문제</button>)}
        </div>
      </section>

      <BottomCTA>
        <button className="btn btn-primary btn-lg" disabled={pool.length === 0} onClick={() => setSession(order(kb, pool).slice(0, count))}>
          {pool.length === 0 ? "풀 문제가 없어요" : `${Math.min(count, pool.length)}문제 풀기`}
        </button>
      </BottomCTA>
    </div>
  );
}

function Session({ quizzes, kb, onExit }: { quizzes: Quiz[]; kb: KB; onExit: () => void }) {
  const lb = useLightbox();
  const [i, setI] = useState(0);
  const [answer, setAnswer] = useState("");
  const [revealed, setRevealed] = useState(false);
  const [feedback, setFeedback] = useState<{ loading: boolean; text?: string; error?: string }>({ loading: false });
  const [results, setResults] = useState<string[]>([]);
  const concepts = new Map(kb.concepts.map((c) => [c.id, c]));

  if (i >= quizzes.length) {
    const o = results.filter((r) => r === "O").length;
    return (
      <>
        <div className="empty">
          <div className="empty-icon">{o === results.length ? "🎉" : "💪"}</div>
          <h1 className="t1">{`${results.length}문제 중 ${o}문제\n맞혔어요`}</h1>
          <p className="sub">{o === results.length ? "다 맞혔어요. 다음엔 새 판을 분석해 봐요." : "틀린 문제는 다음 복습 때 먼저 나와요."}</p>
        </div>
        <BottomCTA><button className="btn btn-primary btn-lg" onClick={onExit}>확인</button></BottomCTA>
      </>
    );
  }

  const q = quizzes[i];
  const grade = async (r: "O" | "△" | "X") => {
    await api.quizResult(q.id, r, answer).catch(() => {});
    setResults((x) => [...x, r]);
    setI(i + 1);
    setAnswer("");
    setRevealed(false);
    setFeedback({ loading: false });
    window.scrollTo(0, 0);
  };
  const askAI = async () => {
    setFeedback({ loading: true });
    try {
      const { feedback: text } = await api.quizFeedback(q.id, answer);
      setFeedback({ loading: false, text });
    } catch (e) {
      setFeedback({ loading: false, error: (e as Error).message });
    }
  };

  return (
    <>
      <div className="progress" style={{ marginBottom: 24 }}><div style={{ width: `${(i / quizzes.length) * 100}%` }} /></div>
      <div className="eyebrow">
        <span>{i + 1} / {quizzes.length}</span><span>·</span><span>{q.type ? QUIZ_TYPES[q.type] ?? q.category : q.category}</span><span>·</span><span>인게임 {q.ingame}</span>
        <button className="chip" style={{ marginLeft: "auto", padding: "4px 10px", fontSize: 13 }} onClick={onExit}>그만하기</button>
      </div>
      <div className="quiz-layout">
      <div className="quiz-media">
        <img className="quiz-img" src={media(q.image)} alt="문제 장면" onClick={() => lb.open([q.image], 0)} />
        <p style={{ margin: "20px 0 24px" }}>{q.situation}</p>
      </div>
      <div>
      <h1 className="t2" style={{ marginBottom: 20 }}>{q.question}</h1>

      <label className="field-label" htmlFor="ans">내 판단</label>
      <textarea
        id="ans"
        className="textarea"
        placeholder="어디로 갈지, 왜 그렇게 생각했는지 적어 보세요"
        value={answer}
        onChange={(e) => setAnswer(e.target.value)}
        disabled={revealed}
      />

      {revealed && (
        <div className="section" style={{ marginTop: 32 }}>
          <div className="card card-blue">
            <div className="card-label">스트리머의 선택</div>
            <div style={{ fontWeight: 700, fontSize: 18 }}>{q.answer}</div>
          </div>
          <p style={{ margin: "20px 0 0" }}>{q.explanation}</p>
          <div className="row" style={{ marginTop: 16 }}>
            {q.concepts.map((id) => <Link key={id} to={`/concepts/${id}`} className="chip">{concepts.get(id)?.name ?? id}</Link>)}
            <Link to={gamePath(q.game_ref, q.ref ?? q.scene)} className="chip">실제 장면 보기</Link>
          </div>

          {answer.trim() && (
            <div style={{ marginTop: 24 }}>
              {feedback.text ? (
                <div className="card card-tight" style={{ whiteSpace: "pre-line" }}>
                  <div className="card-label">Claude 피드백</div>{feedback.text}
                </div>
              ) : (
                <button className="btn btn-ghost btn-block" onClick={askAI} disabled={feedback.loading} aria-busy={feedback.loading}>
                  {feedback.loading ? <>Claude가 읽고 있어요 <Dots /></> : "내 답 Claude에게 채점받기"}
                </button>
              )}
              {feedback.error && <p className="field-error">{feedback.error}</p>}
            </div>
          )}
          <h2 className="section-title" style={{ marginTop: 40 }}>내 판단은 어땠나요?</h2>
          <div className="grade" style={{ marginBottom: 24 }}>
            <button className="btn btn-secondary" onClick={() => grade("O")}>맞았어요<small>다음에 늦게</small></button>
            <button className="btn btn-ghost" onClick={() => grade("△")}>애매해요<small>조금 뒤에</small></button>
            <button className="btn btn-ghost" onClick={() => grade("X")}>틀렸어요<small>다음에 먼저</small></button>
          </div>
        </div>
      )}

      {!revealed && (
        <BottomCTA>
          <button className="btn btn-primary btn-lg" onClick={() => setRevealed(true)}>{answer.trim() ? "정답 보기" : "모르겠어요, 정답 보기"}</button>
        </BottomCTA>
      )}
      </div>
      </div>
    </>
  );
}
