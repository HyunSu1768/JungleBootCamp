import { useState } from "react";
import { Link } from "react-router-dom";
import { api, CATEGORIES, gamePath } from "../api";
import { ErrorView, Loading, PageHead, usePoll } from "../ui";

export default function Rules() {
  const { data, error } = usePoll(api.kb, [], () => false);
  const [cat, setCat] = useState<string | null>(null);
  if (error) return <ErrorView message={error} />;
  if (!data) return <Loading />;

  if (data.rules.length === 0) {
    return (
      <div className="empty">
        <div className="empty-icon">🧭</div>
        <h1 className="t2">아직 원칙이 없어요</h1>
        <p className="sub">{"판을 분석하면 '이런 상황이면 이렇게'가\n여기에 쌓여요"}</p>
      </div>
    );
  }

  const concepts = new Map(data.concepts.map((c) => [c.id, c]));
  const all = [...CATEGORIES.filter((c) => data.rules.some((r) => r.category === c)),
    ...[...new Set(data.rules.map((r) => r.category))].filter((c) => !CATEGORIES.includes(c))];

  return (
    <>
      <PageHead title="상황별 원칙" sub="이런 상황이면, 이렇게 해요" />
      <div className="row" style={{ marginBottom: 32 }}>
        <button className={`chip ${!cat ? "on" : ""}`} onClick={() => setCat(null)}>전체</button>
        {all.map((c) => <button key={c} className={`chip ${cat === c ? "on" : ""}`} onClick={() => setCat(c)}>{c}</button>)}
      </div>
      {all.filter((c) => !cat || c === cat).map((c) => (
        <section key={c} style={{ marginBottom: 48 }}>
          <h2 className="section-title">{c}</h2>
          <div className="stack tile-grid">
            {data.rules.filter((r) => r.category === c).sort((a, b) => b.evidence.length - a.evidence.length).map((r) => (
              <div key={r.id} className="card card-tight">
                <div className="row" style={{ marginBottom: 6 }}>
                  {new Set(r.evidence.map((e) => e.game_ref)).size <= 1 && <span className="badge badge-orange">아직 가설</span>}
                  {[...new Set(r.evidence.map((e) => e.context).filter((x) => x && x !== "솔로랭크"))].map((cx) => <span key={cx} className="badge badge-grey">{cx}</span>)}
                </div>
                <div className="small">{r.when}</div>
                <div style={{ fontWeight: 700, fontSize: 18, marginTop: 4 }}>→ {r.then}</div>
                {r.exceptions.length > 0 && (
                  <div className="small" style={{ marginTop: 10 }}>
                    <b style={{ color: "var(--orange)" }}>예외</b> {r.exceptions.join(" / ")}
                  </div>
                )}
                <div className="row" style={{ marginTop: 14 }}>
                  {r.evidence.map((e, i) => (
                    <Link key={i} to={gamePath(e.game_ref, e.ref ?? e.scene)} className="badge badge-blue">
                      근거 {i + 1}{data.games[e.game_ref] ? ` · ${data.games[e.game_ref].champion}` : ""}
                    </Link>
                  ))}
                  {r.concepts.map((id) => (
                    <Link key={id} to={`/concepts/${id}`} className="badge badge-grey">{concepts.get(id)?.name ?? id}</Link>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </section>
      ))}
    </>
  );
}
