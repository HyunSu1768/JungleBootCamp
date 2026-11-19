import { Link, useParams } from "react-router-dom";
import { api, gamePath } from "../api";
import { ErrorView, Loading, PageHead, ResultBadge, usePoll } from "../ui";

export default function ConceptPage() {
  const { id = "" } = useParams();
  const { data, error } = usePoll(api.kb, [id], () => false);
  if (error) return <ErrorView message={error} />;
  if (!data) return <Loading />;
  const c = data.concepts.find((x) => x.id === id);
  if (!c) return <ErrorView message="개념을 찾을 수 없어요" />;
  const rules = data.rules.filter((r) => r.concepts.includes(c.id));
  const quizzes = data.quizzes.filter((q) => q.concepts.includes(c.id));

  return (
    <>
      <PageHead eyebrow={<><Link to="/concepts">‹ 개념</Link><span>· {c.category}</span></>} title={c.name} sub={c.summary} />

      <div className="concept-layout">
      <div>
      <div className="card">{c.definition}</div>

      {c.criteria.length > 0 && (
        <section className="section">
          <h2 className="section-title">판단 기준</h2>
          <ol className="numbered">{c.criteria.map((x, i) => <li key={i}><span>{x}</span></li>)}</ol>
        </section>
      )}

      {c.exceptions.length > 0 && (
        <section className="section">
          <h2 className="section-title">이럴 땐 달라요</h2>
          <ul className="bullets">{c.exceptions.map((x, i) => <li key={i}>{x}</li>)}</ul>
        </section>
      )}

      {rules.length > 0 && (
        <section className="section">
          <h2 className="section-title">관련 원칙</h2>
          <div className="stack">
            {rules.map((r) => (
              <div key={r.id} className="rule-box" style={{ marginTop: 0 }}>
                <div className="when">{r.when}</div>
                <div className="then">→ {r.then}</div>
              </div>
            ))}
          </div>
        </section>
      )}

      </div>
      <aside>
      <section className="section" style={{ marginTop: 0 }}>
        <h2 className="section-title">실제 사례 {c.examples.length}개</h2>
        <div className="list">
          {c.examples.map((e, i) => {
            const g = data.games[e.game_ref];
            return (
              <Link key={i} to={gamePath(e.game_ref, e.ref ?? e.scene)} className="list-row">
                <div className="list-body">
                  <div className="list-title row" style={{ gap: 6 }}>
                    {g ? `${g.streamer} · ${g.champion}` : e.game_ref} <ResultBadge result={g?.result} />
                    {e.context && e.context !== "솔로랭크" && <span className="badge badge-orange">{e.context}</span>}
                  </div>
                  <div className="list-desc">{e.note}</div>
                </div>
                <span className="chev">›</span>
              </Link>
            );
          })}
        </div>
      </section>

      {quizzes.length > 0 && (
        <section className="section">
          <Link to={`/review?concept=${c.id}`} className="btn btn-secondary btn-block btn-lg">이 개념 문제 {quizzes.length}개 풀기</Link>
        </section>
      )}
      </aside>
      </div>
    </>
  );
}
