import { Link, useNavigate } from "react-router-dom";
import { api, thumbUrl, type VodSummary } from "../api";
import { BottomCTA, Dots, ErrorView, Loading, PageHead, isActive, usePoll } from "../ui";

function status(v: VodSummary) {
  if (v.job && isActive(v.job)) {
    const step = v.job.steps.find((s) => s.status === "running") ?? v.job.steps[0];
    return <span className="badge badge-blue">{v.job.status === "queued" ? "대기 중" : step.name} <Dots /></span>;
  }
  if (v.job?.status === "error") return <span className="badge badge-red">실패</span>;
  if (v.job?.status === "cancelled") return <span className="badge badge-grey">취소됨</span>;
  return null;
}

function desc(v: VodSummary) {
  if (!v.dir) return "영상 정보를 가져오는 중이에요";
  if (!v.games) return v.uploader || "판을 찾는 중이에요";
  return [v.uploader, `${v.games}판`, v.jungle_games !== v.games ? `정글 ${v.jungle_games}판` : null, v.analyzed ? `분석 ${v.analyzed}판` : null]
    .filter(Boolean)
    .join(" · ");
}

export default function Home() {
  const nav = useNavigate();
  const { data, error } = usePoll(api.vods, [], (d) => !!d?.some((v) => isActive(v.job)), 3000);

  if (error) return <ErrorView message={error} />;
  if (!data) return <Loading />;

  if (data.length === 0) {
    return (
      <>
        <div className="empty">
          <div className="empty-icon">🌲</div>
          <h1 className="t1">{"스트리머 영상으로\n정글을 배워요"}</h1>
          <p className="sub">{"숲 다시보기 링크만 넣으면\n판을 찾고, 왜 그렇게 했는지 정리해 드려요"}</p>
        </div>
        <BottomCTA>
          <button className="btn btn-primary btn-lg" onClick={() => nav("/add")}>영상 추가하기</button>
        </BottomCTA>
      </>
    );
  }

  return (
    <>
      <PageHead
        title="프로 영상"
        sub="스트리머 판을 분석하면 판단 포인트가 훈련 문제로 쌓여요"
        actions={<button className="btn btn-primary" onClick={() => nav("/add")}>영상 추가</button>}
      />
      <div className="cards">
        {data.map((v, i) => {
          const to = v.dir ? `/vods/${encodeURIComponent(v.dir)}` : v.job ? `/jobs/${v.job.id}` : "#";
          return (
            <Link key={v.dir ?? v.job?.id ?? i} to={to} className="item-card">
              <div className="thumb-wrap">
                {v.dir && v.games > 0 ? <img className="thumb" src={thumbUrl(v.dir, 1)} alt="" loading="lazy" /> : <div className="icon-circle">🎬</div>}
              </div>
              <div className="list-body">
                <div className="list-title">{v.title}</div>
                <div className="list-desc">{desc(v)}</div>
              </div>
              <div className="item-action">
                {status(v)}
                <span className="chev">›</span>
              </div>
            </Link>
          );
        })}
      </div>
      <BottomCTA mobileOnly>
        <button className="btn btn-primary btn-lg" onClick={() => nav("/add")}>영상 추가하기</button>
      </BottomCTA>
    </>
  );
}
