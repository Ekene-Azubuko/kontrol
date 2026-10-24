"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import {
  Activity,
  ArrowLeftRight,
  Bell,
  Bot,
  ChevronDown,
  ChevronLeft,
  CircleHelp,
  Flame,
  House,
  LayoutDashboard,
  MapPin,
  Menu,
  MessageSquare,
  Radio,
  Send,
  Ambulance,
  Hospital,
  ClipboardList,
  X,
} from "lucide-react";
import { LiveUpdates, useAuth } from "@/lib/api";
import type { Role } from "@/lib/types";
import { branding } from "@/lib/branding";
import { CoordinatorView } from "./coordinator";
import { ResidentView } from "./resident";
const coordinatorLinks = [
  { slug: "overview", label: "Command Center", icon: LayoutDashboard },
  { slug: "incidents", label: "Incidents", icon: Flame },
  { slug: "response-plans", label: "Response Plans", icon: ClipboardList },
  { slug: "dispatch", label: "Fleet & Dispatch", icon: Ambulance },
  { slug: "hospitals", label: "Hospital Network", icon: Hospital },
  { slug: "communications", label: "Communications", icon: Radio },
  { slug: "agents", label: "Agent Operations", icon: Bot },
];
const residentLinks = [
  { slug: "home", label: "Home", icon: House },
  { slug: "updates", label: "Updates", icon: Bell },
  { slug: "report", label: "Report", icon: Send },
  { slug: "help", label: "Find help", icon: MapPin },
  { slug: "assistant", label: "Assistant", icon: MessageSquare },
];

/** Open each portal directly while selecting its built-in application identity. */
export function Workspace({ role, page }: { role: Role; page: string }) {
  const auth = useAuth();
  const interfaceName =
    role === "coordinator" ? branding.command : branding.community;
  const [collapsed, setCollapsed] = useState(false);
  const [mobile, setMobile] = useState(false);
  const [clock, setClock] = useState("");
  useEffect(() => {
    if (auth.role !== role) auth.switchRole(role);
  }, [auth, role]);
  useEffect(() => {
    const tick = () =>
      setClock(new Date().toLocaleTimeString([], { hour12: false }));
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);
  const links = role === "coordinator" ? coordinatorLinks : residentLinks;
  return (
    <div className={`app-shell ${role} ${collapsed ? "collapsed" : ""}`}>
      <aside className={`sidebar ${mobile ? "mobile-open" : ""}`}>
        <Link
          href={`/${role}/${role === "coordinator" ? "overview" : "home"}`}
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
            <small>Live response operations</small>
          </div>
          <ChevronDown size={14} />
        </div>
        <div className="nav-label">
          {role === "coordinator" ? "OPERATIONS" : "YOUR COMMUNITY"}
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
          <Link
            className="portal-link"
            href={
              role === "coordinator"
                ? "/resident/home"
                : "/coordinator/overview"
            }
          >
            <ArrowLeftRight size={16} />
            <span>
              {role === "coordinator" ? branding.community : branding.command}
            </span>
          </Link>
          <button
            className="collapse-control"
            onClick={() => setCollapsed(!collapsed)}
          >
            <ChevronLeft size={16} />
            <span>Collapse sidebar</span>
          </button>
          <div className="profile">
            <div className="avatar">{role === "coordinator" ? "KC" : "KR"}</div>
            <div>
              <strong>{role === "coordinator" ? "Operations desk" : "Report portal"}</strong>
              <small>
                {role === "coordinator"
                  ? "Incident coordinator"
                  : "Community resident"}
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
            <span className="scenario-pill"><span className="live-dot" /> LIVE</span>
            <span className="clock">
              {clock || "—"} <small>LOCAL</small>
            </span>
            <Bell size={17} />
          </div>
        </header>
        {auth.role === role && (
          <>
            <LiveUpdates />
            <div className="page-content">
              {role === "coordinator" ? (
                <CoordinatorView page={page} />
              ) : (
                <ResidentView page={page} />
              )}
            </div>
          </>
        )}
        <footer>
          <span>LIVE OPERATIONS</span>
          <span>
            {branding.product} · Human decisions. Traceable intelligence.
          </span>
        </footer>
      </main>
      {role === "resident" && (
        <nav className="bottom-nav">
          {residentLinks.map(({ slug, label, icon: Icon }) => (
            <Link
              key={slug}
              href={`/resident/${slug}`}
              className={page === slug ? "active" : ""}
            >
              <Icon size={19} />
              <span>{label}</span>
            </Link>
          ))}
        </nav>
      )}
    </div>
  );
}
