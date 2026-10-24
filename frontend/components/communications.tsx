"use client";
import { useState } from "react";
import { CheckCheck, Radio } from "lucide-react";
import { useData } from "@/lib/api";
import type { Communication } from "@/lib/response-types";
import { time } from "@/lib/utils";
import { Badge, Empty, ErrorBox, Loading, Panel, useAction } from "./shared";
import { PageHeading } from "./page-heading";
import { Button } from "./ui/button";
import { PlanDetail } from "./response-plans";

/** Show internal approval-triggered messages without calling any real communication service. */
export function Communications() {
  const query = useData<Communication[]>("/communications");
  const [filter, setFilter] = useState("all");
  const [plan, setPlan] = useState<string | null>(null);
  const action = useAction();
  const rows =
    query.data?.filter(
      (message) => filter === "all" || message.status === filter,
    ) || [];
  return (
    <>
      <PageHeading
        eyebrow="INTERNAL OPERATIONAL LOG"
        title="Communications"
        subtitle="Messages to responders, receiving hospitals and the coordination team."
      />
      <div className="response-intro">
        <Radio size={24} />
        <div>
          <strong>Approval-triggered messages</strong>
          <p>
            Messages are recorded after coordinator approval and when assigned
            vehicles arrive.
          </p>
        </div>
      </div>
      {action.feedback}
      <Panel
        title="Communication log"
        action={
          <select
            aria-label="Communication status"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          >
            <option value="all">All statuses</option>
            <option value="sent">Sent</option>
            <option value="acknowledged">Acknowledged</option>
          </select>
        }
      >
        {query.isLoading && <Loading />}
        {query.error && <ErrorBox message={query.error.message} />}
        {rows.map((message) => (
          <article
            className="communication-row operational-message"
            key={message.id}
          >
            <div className="row">
              <span className="eyebrow">{message.recipient_type}</span>
              <Badge value={message.status} />
            </div>
            <h3>{message.recipient}</h3>
            <p>{message.message}</p>
            <div className="row muted">
              <span>
                {message.incident_title} · {time(message.created_at)}
              </span>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setPlan(message.plan_id)}
              >
                View plan
              </Button>
            </div>
            {message.status !== "acknowledged" && (
              <Button
                size="sm"
                variant="secondary"
                disabled={action.busy}
                onClick={() =>
                  action.act(
                    `/communications/${message.id}/acknowledge`,
                    {},
                    "POST",
                    "Acknowledgement recorded",
                  )
                }
              >
                <CheckCheck size={15} />
                Acknowledge
              </Button>
            )}
          </article>
        ))}
        {!query.isLoading && !rows.length && (
          <Empty>
            Approve a response plan to generate dispatch communications.
          </Empty>
        )}
      </Panel>
      <PlanDetail id={plan} onClose={() => setPlan(null)} />
    </>
  );
}
