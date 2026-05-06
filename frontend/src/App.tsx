// App shell — tiny path-based router so we don't pull in react-router-dom
// for two pages. Listens to `popstate` (browser back/forward) and uses
// `history.pushState` for in-app navigation. The default route ("/" or
// anything not matching /interview) renders the CV Engine.

import { useEffect, useState } from 'react';
import CVGenerator from './pages/CVGenerator';
import InterviewCopilot from './pages/InterviewCopilot';

type Route = '/cv' | '/interview';

function resolveRoute(pathname: string): Route {
  return pathname.startsWith('/interview') ? '/interview' : '/cv';
}

function getCurrentRoute(): Route {
  if (typeof window === 'undefined') return '/cv';
  return resolveRoute(window.location.pathname || '/');
}

export default function App() {
  const [route, setRoute] = useState<Route>(getCurrentRoute);

  useEffect(() => {
    const onPopState = () => setRoute(getCurrentRoute());
    window.addEventListener('popstate', onPopState);
    return () => window.removeEventListener('popstate', onPopState);
  }, []);

  const navigate = (next: Route) => {
    if (next === route) return;
    window.history.pushState({}, '', next);
    setRoute(next);
  };

  return (
    <div>
      <NavBar current={route} onNavigate={navigate} />
      {route === '/interview' ? <InterviewCopilot /> : <CVGenerator />}
    </div>
  );
}

interface NavItem {
  path: Route;
  label: string;
}

const NAV_ITEMS: NavItem[] = [
  { path: '/cv', label: 'CV Engine' },
  { path: '/interview', label: 'Interview Copilot' },
];

function NavBar({
  current,
  onNavigate,
}: {
  current: Route;
  onNavigate: (path: Route) => void;
}) {
  return (
    <nav
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        padding: '12px 24px',
        background: '#fff',
        borderBottom: '1px solid #e2e2e8',
      }}
    >
      <strong style={{ fontSize: 14, marginRight: 16 }}>CareerAI</strong>
      {NAV_ITEMS.map((item) => {
        const active = current === item.path;
        return (
          <a
            key={item.path}
            href={item.path}
            onClick={(e) => {
              e.preventDefault();
              onNavigate(item.path);
            }}
            style={{
              padding: '6px 12px',
              borderRadius: 6,
              fontSize: 14,
              fontWeight: 500,
              textDecoration: 'none',
              color: active ? '#fff' : '#111',
              background: active ? '#111' : 'transparent',
              border: `1px solid ${active ? '#111' : '#e2e2e8'}`,
            }}
          >
            {item.label}
          </a>
        );
      })}
    </nav>
  );
}
