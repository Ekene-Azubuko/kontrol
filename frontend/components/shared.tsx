"use client";
import { useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  ArrowUpRight,
  Check,
  Clock3,
  LoaderCircle,
  Radio,
} from "lucide-react";
import { request, useAuth } from "@/lib/api";
import { time } from "@/lib/utils";
import type { Incident, PublicUpdate, Resource } from "@/lib/types";
import { Button } from "./ui/button";

/** Present status using both text and color for accessible scanning. */
export function Badge({ value }: { value: string }) {
  return <span className={`badge ${value}`}>{value.replaceAll("_", " ")}</span>;
}
export function Empty({ children }: { children: ReactNode }) {
  return (
    <div className="empty">
      <Radio size={24} />
      <p>{children}</p>
    </div>
  );
}
export function Loading() {
  return (
    <div className="empty">
      <LoaderCircle className="spin" size={24} />
      <p>Loading operational records…</p>
    </div>
  );
}
export function ErrorBox({ message }: { message: string }) {
  return (
    <div role="alert" className="error">
      <AlertCircle size={18} />
      {message}
    </div>
  );
}
export function Panel({
  title,
  eyebrow,
  children,
  action,
  className = "",
}: {
  title: string;
  eyebrow?: string;
  children: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <section className={`panel ${className}`}>
      <div className="panel-heading">
        <div>
          {eyebrow && <small>{eyebrow}</small>}
          <h2>{title}</h2>
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}
export function Metric({
  label,
  value,
  detail,
  icon,
  tone = "blue",
}: {
  label: string;
  value: number | string;
  detail: string;
  icon: ReactNode;
  tone?: string;
}) {
  return (
    <div className="metric">
      <div className="metric-top">
        <span>{label}</span>
        <span className={`metric-icon ${tone}`}>{icon}</span>
      </div>
      <strong>{value}</strong>
      <small>{detail}</small>
    </div>
  );
}

/** Centralize mutation feedback and invalidate all role-scoped server records. */
export function useAction() {
  const { token } = useAuth();
  const client = useQueryClient();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  async function act<T>(
    path: string,
    body?: unknown,
    method = "POST",
    message = "Changes saved",
  ) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await request<T>(path, token, method, body);
      await client.invalidateQueries();
      setNotice(message);
      return result;
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Request failed");
      return undefined;
    } finally {
      setBusy(false);
    }
  }
  return {
    act,
    busy,
    error,
    notice,
    feedback: (
      <>
        {error && <ErrorBox message={error} />}
        {notice && (
          <div role="status" className="notice">
            <Check size={16} />
            {notice}
          </div>
        )}
      </>
    ),
  };
}

export function IncidentCard({
  incident,
  onSelect,
}: {
  incident: Incident;
  onSelect: () => void;
}) {
  return (
    <button className="incident-card" onClick={onSelect}>
      <div className="row">
        <Badge value={incident.severity} />
        <span className="mono">{incident.id.slice(0, 8).toUpperCase()}</span>
      </div>
      <h3>{incident.title}</h3>
      <div className="row muted">
        <span>{incident.location}</span>
        <ArrowUpRight size={16} />
      </div>
    </button>
  );
}

/** Render public update content as escaped text with immutable source timestamps. */
export function UpdateCard({
  update,
  following,
  onFollow,
}: {
  update: PublicUpdate;
  following?: boolean;
  onFollow?: () => void;
}) {
  return (
    <article id={update.id} className="update-card">
      <div className="row">
        <span className="official">
          <Check size={13} /> Official scenario update
        </span>
        <Badge value={update.severity} />
      </div>
      <h3>{update.title}</h3>
      <p>{update.body}</p>
      <div className="row muted">
        <span>
          <Clock3 size={13} /> {time(update.published_at)} · {update.audience}
        </span>
        {onFollow && (
          <Button size="sm" variant="ghost" onClick={onFollow}>
            {following ? "Following ✓" : "+ Follow incident"}
          </Button>
        )}
      </div>
    </article>
  );
}

/** Display confirmed resource availability without implying a real emergency service. */
export function ResourceCard({
  resource,
  children,
}: {
  resource: Resource;
  children?: ReactNode;
}) {
  const available = resource.capacity - resource.occupancy;
  return (
    <article id={resource.id} className="resource-card">
      <div className="row">
        <Badge value={resource.category} />
        <span className={available < 10 ? "text-warning" : "text-success"}>
          {available} available
        </span>
      </div>
      <h3>{resource.name}</h3>
      <p className="muted">{resource.location}</p>
      <div className="capacity">
        <div
          style={{
            width: `${resource.capacity ? (resource.occupancy / resource.capacity) * 100 : 0}%`,
          }}
        />
      </div>
      <div className="row muted">
        <small>
          {resource.occupancy} / {resource.capacity} occupied
        </small>
        <small>Confirmed {time(resource.confirmed_at)}</small>
      </div>
      <div className="resource-tags">
        {resource.accessible && <span>Accessible</span>}
        {resource.pet_friendly && <span>Pet friendly</span>}
      </div>
      <small className="muted">{resource.contact}</small>
      {children}
    </article>
  );
}
