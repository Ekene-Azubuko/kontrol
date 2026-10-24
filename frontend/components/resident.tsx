"use client";
import Link from "next/link";
import { useState } from "react";
import {
  Bot,
  ChevronRight,
  MapPin,
  MessageSquare,
  Plus,
  Search,
  Send,
  ShieldCheck,
} from "lucide-react";
import { useData } from "@/lib/api";
import { branding } from "@/lib/branding";
import type { Answer, PublicUpdate, Resource } from "@/lib/types";
import { Empty, ErrorBox, Panel, UpdateCard, useAction } from "./shared";
import { IncidentMap } from "./map";
import { Button } from "./ui/button";
import { PageHeading } from "./page-heading";
import { ResourceWorkspace } from "./resources";
import { ReportFlow } from "./report-flow";

/** Render resident views from published records only, with personal follow filters. */
export function ResidentView({ page }: { page: string }) {
  const updates = useData<PublicUpdate[]>("/updates");
  const subscriptions = useData<string[]>("/subscriptions");
  const resources = useData<Resource[]>("/resources");
  const [location, setLocation] = useState("All Cedar Valley");
  const [filter, setFilter] = useState("all");
  const [selected, setSelected] = useState<string | null>(null);
  const action = useAction();
  const rows = (updates.data || []).filter(
    (item) =>
      (filter !== "following" ||
        subscriptions.data?.includes(item.incident_id)) &&
      (filter !== "nearby" ||
        location === "All Cedar Valley" ||
        item.audience === location ||
        item.audience === "All Cedar Valley"),
  );
  const nearby = (updates.data || []).filter(
    (item) =>
      location === "All Cedar Valley" ||
      item.audience === location ||
      item.audience === "All Cedar Valley",
  );
  const locations = Array.from(
    new Set([
      ...(updates.data || []).map((item) => item.audience),
      ...(resources.data || []).map((item) => item.location),
    ]),
  );
  async function follow(update: PublicUpdate) {
    const following = subscriptions.data?.includes(update.incident_id);
    await action.act(
      `/subscriptions/${update.incident_id}`,
      undefined,
      following ? "DELETE" : "PUT",
      following ? "Incident unfollowed" : "Incident followed",
    );
  }
  const locationSelector = (
    <label className="location-selector">
      <MapPin size={16} />
      <select
        aria-label="Your location"
        value={location}
        onChange={(event) => setLocation(event.target.value)}
      >
        <option>All Cedar Valley</option>
        {locations
          .filter((value) => value !== "All Cedar Valley")
          .map((value) => (
            <option key={value}>{value}</option>
          ))}
      </select>
    </label>
  );
  return (
    <>
      {page === "home" && (
        <>
          <PageHeading
            eyebrow="YOUR COMMUNITY, CONNECTED"
            title="See something? Share an observation."
            subtitle="Submit an incident and follow its response status in Kontrol Community."
            action={locationSelector}
          />
          <div className="resident-alert">
            <ShieldCheck size={23} />
            <div>
              <strong>Report incidents as soon as you observe them</strong>
              <p>
                Kontrol sends your report to the response team and starts agent
                assessment immediately.
              </p>
            </div>
            <span className="badge high">LIVE</span>
          </div>
          <div className="quick-actions">
            <Link href="/resident/report">
              <span className="quick-icon">
                <Plus size={22} />
              </span>
              <div>
                <strong>Report an observation</strong>
                <small>Share what you see</small>
              </div>
              <ChevronRight size={18} />
            </Link>
            <Link href="/resident/help">
              <span className="quick-icon green">
                <MapPin size={22} />
              </span>
              <div>
                <strong>Find community resources</strong>
                <small>Shelter, supplies, and support</small>
              </div>
              <ChevronRight size={18} />
            </Link>
            <Link href="/resident/assistant">
              <span className="quick-icon purple">
                <MessageSquare size={22} />
              </span>
              <div>
                <strong>Ask Kontrol</strong>
                <small>Answers with published sources</small>
              </div>
              <ChevronRight size={18} />
            </Link>
          </div>
          <Panel
            title="Your area at a glance"
            action={<span className="official">Published records only</span>}
          >
            <IncidentMap
              items={nearby.map((update) => ({ ...update, id: update.id }))}
              onSelect={setSelected}
            />
            {selected &&
              nearby
                .filter((item) => item.id === selected)
                .map((update) => (
                  <UpdateCard
                    key={update.id}
                    update={update}
                    following={subscriptions.data?.includes(update.incident_id)}
                    onFollow={() => follow(update)}
                  />
                ))}
          </Panel>
          <Panel
            title="Latest official updates"
            action={
              <Link className="text-link" href="/resident/updates">
                View all updates <ChevronRight size={14} />
              </Link>
            }
          >
            <div className="updates-grid">
              {nearby.slice(0, 4).map((update) => (
                <UpdateCard
                  key={update.id}
                  update={update}
                  following={subscriptions.data?.includes(update.incident_id)}
                  onFollow={() => follow(update)}
                />
              ))}
            </div>
            {!nearby.length && (
              <Empty>No published updates for the selected area.</Empty>
            )}
          </Panel>
        </>
      )}
      {page === "updates" && (
        <>
          <PageHeading
            eyebrow="OFFICIAL SCENARIO INFORMATION"
            title="Updates from your community"
            subtitle="Every update is reviewed and published by an authorized coordinator."
            action={locationSelector}
          />
          <Panel title="Published updates">
            <div className="tabs">
              {["all", "nearby", "following"].map((value) => (
                <button
                  key={value}
                  className={filter === value ? "active" : ""}
                  onClick={() => setFilter(value)}
                >
                  {value}
                </button>
              ))}
            </div>
            <div className="updates-grid">
              {rows.map((update) => (
                <UpdateCard
                  key={update.id}
                  update={update}
                  following={subscriptions.data?.includes(update.incident_id)}
                  onFollow={() => follow(update)}
                />
              ))}
            </div>
            {!rows.length && (
              <Empty>
                No published updates match this view. Follow an incident to keep
                it here.
              </Empty>
            )}
          </Panel>
        </>
      )}
      {page === "report" && <ReportFlow />}
      {page === "help" && <ResourceWorkspace />}
      {page === "assistant" && (
        <>
          <PageHeading
            eyebrow="GROUNDED IN PUBLISHED INFORMATION"
            title="Ask Kontrol"
            subtitle="Explore fictional scenario information with links to its approved sources."
          />
          <Assistant />
        </>
      )}
      {action.feedback}
      {updates.error && ["home", "updates"].includes(page) && (
        <ErrorBox message={updates.error.message} />
      )}
    </>
  );
}

/** Answer through bounded backend retrieval and show each underlying source record. */
export function Assistant({ coordinator = false }: { coordinator?: boolean }) {
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState<
    { question: string; response: Answer }[]
  >([]);
  const action = useAction();
  async function ask(value: string) {
    if (!value.trim()) return;
    const result = await action.act<Answer>(
      "/assistant",
      { question: value },
      "POST",
      "",
    );
    if (result) {
      setMessages((previous) => [
        ...previous,
        { question: value, response: result },
      ]);
      setQuestion("");
    }
  }
  return (
    <Panel
      title={`${coordinator ? branding.command : branding.community} assistant`}
      action={
        <span className="badge verified">
          <ShieldCheck size={12} />
          Published sources
        </span>
      }
    >
      <div className="assistant">
        <div className="assistant-intro">
          <span className="assistant-logo">
            <Bot size={30} />
          </span>
          <h2>Clarity starts with a question.</h2>
          <p>
            I can find approved scenario updates and published resource
            availability.
            <br />I cannot provide real-world emergency instructions.
          </p>
          <div className="suggestions">
            {[
              "Are there road closures near me?",
              "Where can I find shelter?",
              "What changed in the last hour?",
            ].map((value) => (
              <button
                key={value}
                disabled={action.busy}
                onClick={() => ask(value)}
              >
                <Search size={14} />
                {value}
              </button>
            ))}
          </div>
        </div>
        <div className="chat-messages" aria-live="polite">
          {messages.map((message, index) => (
            <div className="chat-turn" key={index}>
              <div className="user-message">{message.question}</div>
              <div className="assistant-message">
                <Bot size={20} />
                <div>
                  <p>{message.response.answer}</p>
                  {message.response.sources.map((source) => (
                    <Link
                      className="source-card"
                      key={source.id}
                      href={source.href}
                    >
                      <strong>
                        {source.title} <ChevronRight size={14} />
                      </strong>
                      <p>{source.text}</p>
                    </Link>
                  ))}
                </div>
              </div>
            </div>
          ))}
        </div>
        {action.busy && <p className="muted">Checking published records…</p>}
        <form
          className="chat-input"
          onSubmit={(event) => {
            event.preventDefault();
            void ask(question);
          }}
        >
          <input
            aria-label="Ask a question"
            placeholder="Ask about published scenario updates or resources…"
            value={question}
            maxLength={1000}
            minLength={3}
            onChange={(event) => setQuestion(event.target.value)}
          />
          <Button
            size="icon"
            aria-label="Send question"
            disabled={action.busy || question.length < 3}
          >
            <Send size={18} />
          </Button>
        </form>
        <small className="muted">
          Responses reference coordinator-approved records in Kontrol.
        </small>
        {action.feedback}
      </div>
    </Panel>
  );
}
