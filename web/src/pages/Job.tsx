import { useEffect, useRef } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { BottomCTA, ErrorView, JobSteps, Loading, PageHead, isActive, usePoll } from "../ui";

const TITLES = { scan: "영상을 훑어보고 있어요", redetect: "판을 다시 찾고 있어요", analyze: "판을 분석하고 있어요" };
const DONE = { scan: "판을 다 찾았어요", redetect: "판을 다시 찾았어요", analyze: "분석이 끝났어요" };

export default function JobPage() {
  const { id = "" } = useParams();
  const { data: job, error } = usePoll(() => api.job(id), [id], (d) => isActive(d), 2000);
  const logRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = logRef.current;
    if (el && el.scrollHeight - el.scrollTop - el.clientHeight < 120) el.scrollTop = el.scrollHeight;
  }, [job?.log?.length]);

  if (error) return <ErrorView message={error} />;
  if (!job) return <Loading />;

  const title = job.status === "done" ? DONE[job.kind] : job.status === "error" ? "중간에 멈췄어요" : job.status === "cancelled" ? "작업을 취소했어요" : TITLES[job.kind];
  const next = job.vod
    ? job.kind === "analyze" && job.status === "done"
      ? `/vods/${encodeURIComponent(job.vod)}/${job.game}`
      : `/vods/${encodeURIComponent(job.vod)}`
    : null;

  return (
    <>
      <PageHead
        eyebrow={job.vod ? <Link to={`/vods/${encodeURIComponent(job.vod)}`}>‹ 영상으로</Link> : <Link to="/vods">‹ 목록으로</Link>}
        title={title}
        sub={job.kind === "analyze" ? `${job.game}판` : job.url}
      />
      <div className="job-layout">
      <div>
      <div className="card"><JobSteps job={job} detailLink={false} /></div>

      {job.summary && job.status === "done" && (
        <div className="card card-blue section" style={{ whiteSpace: "pre-line" }}>
          <div className="card-label">Claude가 남긴 말</div>
          {job.summary}
        </div>
      )}

      </div>
      <section className="section" style={{ marginTop: 0 }}>
        <h2 className="section-title mobile-only" style={{ marginTop: 40 }}>진행 기록</h2>
        <div className="log" ref={logRef}>{(job.log ?? []).join("\n") || "아직 기록이 없어요"}</div>
      </section>
      </div>

      {next && (
        <BottomCTA>
          <Link to={next} className={`btn btn-lg ${job.status === "done" ? "btn-primary" : "btn-ghost"}`}>
            {job.kind === "analyze" && job.status === "done" ? "분석 결과 보기" : "영상으로 가기"}
          </Link>
        </BottomCTA>
      )}
    </>
  );
}
