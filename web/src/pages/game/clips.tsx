import { createContext, useContext, useEffect, useMemo, useRef, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { media, secs, type Analysis } from "../../api";
import { usePlayer, type Clip } from "./Player";
import { groupOf } from "./Timeline";

export type ClipGroup = "turns" | "fights" | "tps" | "reviews";
type Clips = Record<ClipGroup, Clip[]>;

const isTime = (t?: string | null): t is string => !!t && /^\d+(:\d{1,2}){1,2}$/.test(t.trim());

function median(xs: number[]) {
  const s = [...xs].sort((a, b) => a - b);
  return s.length ? s[Math.floor(s.length / 2)] : null;
}

/** 분석 결과와 game.json으로 영상 구간들을 만든다. 영상 정보가 없으면 null */
export function buildClips(a: Analysis, dir: string, n: number, meta: Record<string, unknown>): Clips | null {
  const videoStart = meta.video_start as string | undefined;
  if (!isTime(videoStart)) return null;
  const base = secs(videoStart);
  const src = media(`${dir}/game${n}/video.mp4`);

  // 인게임 시각 → VOD 시각 차이. 턴, 교전, 변곡점에 같이 적힌 두 시각으로 구한다
  const diffs: number[] = [];
  for (const t of a.turns?.ally ?? []) if (isTime(t.vod_from) && isTime(t.from)) diffs.push(secs(t.vod_from) - secs(t.from));
  for (const f of a.fights ?? []) if (isTime(f.vod) && isTime(f.ingame)) diffs.push(secs(f.vod) - secs(f.ingame));
  for (const p of a.operations?.turning_points ?? []) if (isTime(p.vod) && isTime(p.ingame)) diffs.push(secs(p.vod) - secs(p.ingame));
  const off = median(diffs) ?? (isTime(meta.start as string) ? secs(meta.start as string) : base);

  const turns: Clip[] = (a.turns?.ally ?? []).map((t) => ({
    id: t.id, kind: "턴", title: `${t.id.toUpperCase()} · ${t.from} – ${t.to}`, sub: t.intent,
    src, base, ingameOffset: off,
    start: off + secs(t.from), end: off + secs(t.to),
    marks: t.actions.filter((x) => isTime(x.t)).map((x) => ({
      at: off + secs(x.t), time: x.t, label: x.label, group: groupOf(x.kind),
      sub: [x.where && x.where !== x.label ? x.where : null, x.result].filter(Boolean).join(" · ") || undefined,
    })),
  }));

  const point = (id: string, kind: string, title: string, sub: string | undefined, ingame: string, vod: string, before: number, after: number): Clip => {
    const at = isTime(vod) ? secs(vod) : off + secs(ingame);
    return { id, kind, title: `${ingame} · ${title}`, sub, src, base, ingameOffset: off, start: at - before, end: at + after,
      marks: [{ at, time: ingame, label: title, sub }] };
  };
  const fights = (a.fights ?? []).filter((f) => isTime(f.vod) || isTime(f.ingame))
    .map((f) => point(f.id, "교전", f.title, f.choice, f.ingame, f.vod, 8, 15));
  const tps = (a.operations?.turning_points ?? []).map((p, i) => ({ p, id: `p${i + 1}` }))
    .filter(({ p }) => isTime(p.vod) || isTime(p.ingame))
    .map(({ p, id }) => point(id, "변곡점", p.title, p.what, p.ingame, p.vod, 10, 15));

  // 리플레이 피드백: 구간마다 따로 받은 review/seg<i>.mp4
  const segs = ((meta.reviews as { from: string; to: string }[] | undefined) ?? []).filter((s) => isTime(s.from) && isTime(s.to));
  const comments = (a.review?.comments ?? []).filter((c) => isTime(c.vod)).sort((x, y) => secs(x.vod) - secs(y.vod));
  const reviews: Clip[] = [];
  for (const c of comments) {
    const v = secs(c.vod);
    const i = segs.findIndex((s) => secs(s.from) - 5 <= v && v <= secs(s.to) + 5);
    if (i < 0) continue;
    const seg = segs[i];
    const same = comments.filter((x) => { const w = secs(x.vod); return secs(seg.from) - 5 <= w && w <= secs(seg.to) + 5; });
    const next = same.find((x) => secs(x.vod) > v);
    reviews.push({
      id: c.id, kind: "피드백", title: `${c.kind} · ${c.point}`, sub: c.ingame ? `리플레이 인게임 ${c.ingame}` : undefined,
      src: media(`${dir}/game${n}/review/seg${i + 1}.mp4`), base: secs(seg.from),
      start: v, end: next ? secs(next.vod) : Math.min(v + 40, secs(seg.to)),
      marks: same.map((x) => ({ at: secs(x.vod), time: x.ingame ?? x.vod, label: `“${x.said}”`, sub: x.kind })),
    });
  }
  return { turns, fights, tps, reviews };
}

const Ctx = createContext<{ play: (g: ClipGroup, id: string, atVod?: number) => void; has: (g: ClipGroup, id: string) => boolean; offset: (g: ClipGroup, id: string) => number | undefined }>({
  play: () => {}, has: () => false, offset: () => undefined,
});
export const useClips = () => useContext(Ctx);

export function ClipsProvider({ clips, children }: { clips: Clips | null; children: ReactNode }) {
  const open = usePlayer();
  const value = useMemo(() => ({
    has: (g: ClipGroup, id: string) => !!clips?.[g].some((c) => c.id === id),
    offset: (g: ClipGroup, id: string) => clips?.[g].find((c) => c.id === id)?.ingameOffset,
    play: (g: ClipGroup, id: string, atVod?: number) => {
      if (!clips) return;
      const i = clips[g].findIndex((c) => c.id === id);
      if (i >= 0) open(clips[g], i, atVod);
    },
  }), [clips, open]);

  // ?play=t2 (f1, p1, r1)로 들어오면 그 구간 영상을 바로 연다
  const [params] = useSearchParams();
  const opened = useRef(false);
  useEffect(() => {
    const id = params.get("play");
    if (!id || !clips || opened.current) return;
    const g: ClipGroup = id.startsWith("t") ? "turns" : id.startsWith("f") ? "fights" : id.startsWith("p") ? "tps" : "reviews";
    opened.current = true;
    value.play(g, id);
  }, [params, clips, value]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

/** "▶ 영상" 버튼. 영상이 없는 판이면 안 보인다 */
export function PlayButton({ group, id, label = "영상으로 보기" }: { group: ClipGroup; id: string; label?: string }) {
  const { play, has } = useClips();
  if (!has(group, id)) return null;
  return (
    <button className="play-btn" onClick={(e) => { e.stopPropagation(); play(group, id); }}>
      <span aria-hidden>▶</span> {label}
    </button>
  );
}
