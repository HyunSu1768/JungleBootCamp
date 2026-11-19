import { useState } from "react";
import { Link } from "react-router-dom";
import { api, CATEGORIES } from "../api";
import { ErrorView, Loading, PageHead, usePoll } from "../ui";

export default function Concepts() {
  const { data, error } = usePoll(api.kb, [], () => false);
  const [cat, setCat] = useState<string | null>(null);
  if (error) return <ErrorView message={error} />;
  if (!data) return <Loading />;

  if (data.concepts.length === 0) {
    return (
      <div className="empty">
        <div className="empty-icon">📚</div>
        <h1 className="t2">아직 배운 개념이 없어요</h1>
        <p className="sub">{"판을 분석하면 나온 개념이 여기에 쌓여요.\n같은 개념이 또 나오면 사례가 늘어나요."}</p>
      </div>
    );
  }

  const cats = CATEGORIES.filter((c) => data.concepts.some((x) => x.category === c));
  const extra = [...new Set(data.concepts.map((c) => c.category))].filter((c) => !CATEGORIES.includes(c));
  const shown = [...cats, ...extra].filter((c) => !cat || c === cat);

  return (
    <>
      <PageHead title="개념" sub={`분석하면서 나온 개념 ${data.concepts.length}개예요`} />
      <div className="row" style={{ marginBottom: 32 }}>
        <button className={`chip ${!cat ? "on" : ""}`} onClick={() => setCat(null)}>전체</button>
        {[...cats, ...extra].map((c) => (
          <button key={c} className={`chip ${cat === c ? "on" : ""}`} onClick={() => setCat(c)}>{c}</button>
        ))}
      </div>
      {shown.map((c) => (
        <section key={c} style={{ marginBottom: 40 }}>
          <h2 className="section-title">{c}</h2>
          <div className="list tile-grid">
            {data.concepts.filter((x) => x.category === c).sort((x, y) => y.examples.length - x.examples.length).map((x) => (
              <Link key={x.id} to={`/concepts/${x.id}`} className="list-row tile">
                <div className="list-body">
                  <div className="list-title">{x.name}</div>
                  <div className="list-desc">{x.summary}</div>
                </div>
                <div className="list-right">
                  <span className="badge badge-grey">사례 {x.examples.length}</span>
                  <span className="chev">›</span>
                </div>
              </Link>
            ))}
          </div>
        </section>
      ))}
    </>
  );
}
