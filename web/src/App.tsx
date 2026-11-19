import { useEffect, useState } from "react";
import { Link, Navigate, NavLink, Route, Routes, useLocation } from "react-router-dom";
import { api, type AppInfo } from "./api";
import { LightboxProvider } from "./ui";
import Home from "./pages/Home";
import AddVod from "./pages/AddVod";
import VodPage from "./pages/Vod";
import GamePage from "./pages/Game";
import JobPage from "./pages/Job";
import Concepts from "./pages/Concepts";
import ConceptPage from "./pages/Concept";
import Rules from "./pages/Rules";
import Review from "./pages/Review";
import Train from "./pages/Train";
import Mine from "./pages/Mine";
import Welcome from "./pages/Welcome";
import SettingsPage from "./pages/Settings";

const TABS = [
  { to: "/", label: "훈련", end: true },
  { to: "/mine", label: "내 게임" },
  { to: "/vods", label: "프로 영상" },
  { to: "/concepts", label: "지식" },
];

/** 지식 탭 안의 하위 메뉴 */
const KNOWLEDGE = [
  { to: "/concepts", label: "개념" },
  { to: "/rules", label: "상황별 원칙" },
  { to: "/review", label: "서술형 복습" },
];

function ScrollTop() {
  const { pathname, hash } = useLocation();
  useEffect(() => {
    if (!hash) window.scrollTo(0, 0);
  }, [pathname, hash]);
  return null;
}

export default function App() {
  const { pathname } = useLocation();
  const [app, setApp] = useState<AppInfo | null>(null);
  useEffect(() => { void api.appInfo().then(setApp).catch(() => {}); }, [pathname === "/welcome"]);
  // 데스크톱 앱 첫 실행: 온보딩(Claude 연결, 티어, 녹화)부터
  if (app?.desktop && !app.settings.onboarded && pathname !== "/welcome") return <Navigate to="/welcome" replace />;
  const section = (to: string) =>
    to === "/" ? pathname === "/"
    : to === "/vods" ? /^\/(vods|add|jobs)/.test(pathname)
    : to === "/concepts" ? /^\/(concepts|rules|review)/.test(pathname)
    : pathname.startsWith(to);
  const inKnowledge = section("/concepts");
  return (
    <LightboxProvider>
      <ScrollTop />
      <nav className="nav">
        <div className="nav-inner">
          <Link to="/" className="brand">
            <span className="brand-mark">정</span>
            <span className="brand-text">정글러훈련소</span>
          </Link>
          <div className="nav-tabs" hidden={pathname === "/welcome"}>
            {TABS.map((t) => (
              <NavLink
                key={t.to}
                to={t.to}
                end={t.end}
                className={() => `tab ${section(t.to) ? "active" : ""}`}
              >
                {t.label}
              </NavLink>
            ))}
          </div>
          <NavLink to="/settings" className={() => `nav-gear ${pathname === "/settings" ? "active" : ""}`} aria-label="설정">⚙︎</NavLink>
        </div>
      </nav>
      {inKnowledge && (
        <div className="subnav">
          {KNOWLEDGE.map((k) => (
            <NavLink key={k.to} to={k.to} className={() => `subtab ${pathname.startsWith(k.to) ? "on" : ""}`}>{k.label}</NavLink>
          ))}
        </div>
      )}
      <main className="page">
        <Routes>
          <Route path="/" element={<Train />} />
          <Route path="/vods" element={<Home />} />
          <Route path="/mine" element={<Mine />} />
          <Route path="/welcome" element={<Welcome />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/mine/:id" element={<GamePage />} />
          <Route path="/add" element={<AddVod />} />
          <Route path="/vods/:dir" element={<VodPage />} />
          <Route path="/vods/:dir/:n" element={<GamePage />} />
          <Route path="/jobs/:id" element={<JobPage />} />
          <Route path="/concepts" element={<Concepts />} />
          <Route path="/concepts/:id" element={<ConceptPage />} />
          <Route path="/rules" element={<Rules />} />
          <Route path="/review" element={<Review />} />
          <Route path="*" element={<div className="empty"><h2 className="t2">없는 페이지예요</h2></div>} />
        </Routes>
      </main>
    </LightboxProvider>
  );
}
