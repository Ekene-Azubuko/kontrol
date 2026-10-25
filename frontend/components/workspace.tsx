"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import {
  Activity,
  Bell,
  Bot,
  ChevronDown,
  ChevronLeft,
  CircleHelp,
  Flame,
  LayoutDashboard,
  Menu,
  Radio,
  Ambulance,
  Hospital,
  ClipboardList,
  X,
} from "lucide-react";
import { LiveUpdates, useAuth } from "@/lib/api";
import type { Role } from "@/lib/types";
import { branding } from "@/lib/branding";
import { CoordinatorView } from "./coordinator";
const coordinatorLinks = [
  { slug: "calls", label: "Recorded Calls", icon: Radio },
  { slug: "overview", label: "Command Center", icon: LayoutDashboard },
  { slug: "incidents", label: "Incidents", icon: Flame },
  { slug: "response-plans", label: "Response Plans", icon: ClipboardList },
  { slug: "dispatch", label: "Fleet & Dispatch", icon: Ambulance },
  { slug: "hospitals", label: "Hospital Network", icon: Hospital },
  { slug: "communications", label: "Communications", icon: Radio },
  { slug: "agents", label: "Agent Operations", icon: Bot },
];
/** Render the dispatcher exercise workspace with its built-in local identity. */
export function Workspace({ role, page }: { role: Role; page: string }) {
  const auth = useAuth();
  const interfaceName = branding.command;
  const [collapsed, setCollapsed] = useState(false);
  const [mobile, setMobile] = useState(false);
  const [clock, setClock] = useState("");
  useEffect(() => {
    const tick = () =>
      setClock(new Date().toLocaleTimeString([], { hour12: false }));
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);
  const links = coordinatorLinks;
  return (
    <div className={`app-shell ${role} ${collapsed ? "collapsed" : ""}`}>
      <aside className={`sidebar ${mobile ? "mobile-open" : ""}`}>
        <Link
          href="/coordinator/overview"
          className="brand"
        >
          <span className="brand-mark">
            <Activity size={23} />
          </span>
          <span>
            {branding.product.toUpperCase()}
            <small>EMERGENCY INTELLIGENCE</small>
          </span>
        </Link>
        <button
          className="close-mobile button ghost"
          onClick={() => setMobile(false)}
          aria-label="Close menu"
        >
          <X />
        </button>
        <div className="workspace-switch">
          <span className="workspace-avatar">SF</span>
          <div>
            <strong>{interfaceName}</strong>
            <small>Dispatcher exercise workspace</small>
          </div>
          <ChevronDown size={14} />
        </div>
        <div className="nav-label">
          OPERATIONS
        </div>
        <nav>
          {links.map(({ slug, label, icon: Icon }) => (
            <Link
              key={slug}
              href={`/${role}/${slug}`}
              className={page === slug ? "active" : ""}
              onClick={() => setMobile(false)}
            >
              <Icon size={18} />
              <span>{label}</span>
              {slug === "agents" && <i className="live-dot" />}
            </Link>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <button
            className="collapse-control"
            onClick={() => setCollapsed(!collapsed)}
          >
            <ChevronLeft size={16} />
            <span>Collapse sidebar</span>
          </button>
          <div className="profile">
            <div className="avatar">KD</div>
            <div>
              <strong>Operations desk</strong>
              <small>
                Dispatcher
              </small>
            </div>
              <CircleHelp size={16} />
          </div>
        </div>
      </aside>
      <main>
        <header className="topbar">
          <div className="row">
            <button
              className="mobile-menu button ghost"
              onClick={() => setMobile(true)}
              aria-label="Open menu"
            >
              <Menu size={20} />
            </button>
            <span className="breadcrumb">
              {interfaceName} <span>/</span>{" "}
              <strong>{links.find((item) => item.slug === page)?.label}</strong>
            </span>
          </div>
          <div className="topbar-right">
            <span className="scenario-pill"><span className="live-dot" /> SIMULATION</span>
            <span className="clock">
              {clock || "—"} <small>LOCAL</small>
            </span>
            <Bell size={17} />
          </div>
        </header>
        <div className="simulation-banner" role="note">SIMULATION (NOT FOR EMERGENCY USE) · Fictional recordings and simulated resource assignments</div>
        {auth.role === role && (
          <>
            <LiveUpdates />
            <div className="page-content">
              <CoordinatorView page={page} />
            </div>
          </>
        )}
        <footer>
          <span>SIMULATION (NOT FOR EMERGENCY USE)</span>
          <span>
            {branding.product} · Human decisions. Traceable intelligence.
          </span>
        </footer>
      </main>

    </div>
  );
}
