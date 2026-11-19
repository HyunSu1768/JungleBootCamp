import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { BottomCTA, Dots, PageHead } from "../ui";

export default function AddVod() {
  const nav = useNavigate();
  const [url, setUrl] = useState("");
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);
  const valid = /^https?:\/\/\S+$/.test(url.trim());

  const submit = async () => {
    if (!valid || busy) return;
    setBusy(true);
    try {
      const job = await api.addVod(url.trim());
      nav(`/jobs/${job.id}`, { replace: true });
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  };

  return (
    <div className="narrow-wrap">
      <PageHead title={"숲 다시보기 링크를\n붙여넣어 주세요"} />
      <label className="field-label" htmlFor="url">다시보기 링크</label>
      <input
        id="url"
        className="input"
        inputMode="url"
        autoFocus
        placeholder="https://vod.sooplive.co.kr/player/..."
        value={url}
        onChange={(e) => {
          setUrl(e.target.value);
          setError(undefined);
        }}
        onKeyDown={(e) => e.key === "Enter" && submit()}
        aria-invalid={!!error}
      />
      {error ? <p className="field-error">{error}</p> : (
        <p className="field-help">8시간짜리 방송도 괜찮아요. 저화질로 먼저 훑어보고 게임 판을 찾아요.</p>
      )}

      <div className="card section">
        <div className="card-label">이렇게 진행돼요</div>
        <ol className="numbered">
          <li><div><b>영상 훑어보기</b><div className="small">방송 전체를 저화질로 받아 1분 간격으로 훑어봐요</div></div></li>
          <li><div><b>판 찾기</b><div className="small">Claude가 픽창과 게임 화면으로 판을 나눠요</div></div></li>
          <li><div><b>판 골라서 분석</b><div className="small">고른 판만 고화질로 받아 밴픽, 동선, 교전을 분석해요</div></div></li>
        </ol>
      </div>

      <BottomCTA>
        <button className="btn btn-primary btn-lg" disabled={!valid || busy} onClick={submit} aria-busy={busy}>
          {busy ? <Dots /> : "시작하기"}
        </button>
      </BottomCTA>
    </div>
  );
}
