import { NavLink, Outlet } from "react-router-dom";

const primaryLinks = [
  { to: "/live", label: "Live Play" },
  { to: "/replay", label: "Replay Lab" },
];

const advancedLinks = [
  { to: "/", label: "Optimize", end: true },
  { to: "/explore", label: "Explore" },
  { to: "/diagnostics", label: "Diagnostics" },
];

function NavGroup({
  label,
  links,
}: {
  label: string;
  links: { to: string; label: string; end?: boolean }[];
}) {
  return (
    <div className="nav-group">
      <div className="nav-group-label">{label}</div>
      <ul className="nav-list">
        {links.map((l) => (
          <li key={l.to}>
            <NavLink
              to={l.to}
              end={l.end}
              className={({ isActive }) =>
                isActive ? "nav-link nav-link-active" : "nav-link"
              }
            >
              {l.label}
            </NavLink>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function AppShell() {
  return (
    <div className="app-shell">
      <nav className="app-nav" aria-label="Main">
        <div className="brand">
          <div className="brand-name">Roulette Optimizer</div>
          <div className="brand-sub">Dynamic Goal-Directed</div>
        </div>
        <div className="nav-groups">
          <NavGroup label="Primary" links={primaryLinks} />
          <NavGroup label="Advanced" links={advancedLinks} />
        </div>
      </nav>
      <main className="app-main">
        <div className="page-workspace">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
