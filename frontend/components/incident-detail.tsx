"use client";
import { useState } from "react";
import { ArrowRight, ClipboardList } from "lucide-react";
import { useData } from "@/lib/api";
import type { Dossier } from "@/lib/types";
import type { ResponsePlan } from "@/lib/response-types";
import { time } from "@/lib/utils";
import { Badge, Empty, ErrorBox, Loading, useAction } from "./shared";
import { Drawer } from "./ui/dialog";
import { Button } from "./ui/button";
import { PlanCard, PlanDetail } from "./response-plans";

/** Preserve source reports and history while centering the incident's response plan. */
export function IncidentDetail({
  id,
  onClose,
}: {
  id: string | null;
  onClose: () => void;
}) {
  const dossier = useData<Dossier>(`/incidents/${id}`, !!id);
  const plans = useData<ResponsePlan[]>(
    `/response-plans?incident_id=${id}`,
    !!id,
  );
  const [tab, setTab] = useState("Response");
  const [planId, setPlanId] = useState<string | null>(null);
  const action = useAction();
  const item = dossier.data;
  const latest = plans.data?.[0];
  return (
    <>
      <Drawer
        open={!!id && !planId}
        onClose={onClose}
        title="Incident response"
      >
        {dossier.isLoading ? (
          <Loading />
        ) : dossier.error ? (
          <ErrorBox message={dossier.error.message} />
        ) : (
          item && (
            <>
              <div className="detail-header">
                <div className="row">
                  <Badge value={item.severity} />
                  <span className="mono">
                    INC-{item.id.slice(0, 8).toUpperCase()}
                  </span>
                </div>
                <h1>{item.title}</h1>
                <p className="muted">
                  {item.location} · {item.reported_casualties ?? "Unknown"}{" "}
                  reported injured
                </p>
                <Badge value={item.response_status} />
              </div>
              <div className="tabs">
                {["Response", "Reports", "History"].map((label) => (
                  <button
                    key={label}
                    className={tab === label ? "active" : ""}
                    onClick={() => setTab(label)}
                  >
                    {label}
                  </button>
                ))}
              </div>
              <div className="detail-section">
                {tab === "Response" && (
                  <>
                    <h3>Incident assessment</h3>
                    <p>{item.summary}</p>
                    <div className="callout">
                      Response requirements are advisory until a coordinator
                      approves a plan.
                    </div>
                    <h3>Response plan</h3>
                    {plans.data?.map((plan) => (
                      <PlanCard
                        key={plan.id}
                        plan={plan}
                        onSelect={() => setPlanId(plan.id)}
                      />
                    ))}
                    {!latest && (
                      <Empty>No response plan has been generated yet.</Empty>
                    )}
                    {(!latest ||
                      ["rejected", "cancelled"].includes(latest.status)) && (
                      <Button
                        disabled={action.busy}
                        onClick={async () => {
                          const plan = await action.act<ResponsePlan>(
                            `/incidents/${item.id}/plan`,
                            {
                              note: "Coordinator requested an incident response plan",
                            },
                          );
                          if (plan) setPlanId(plan.id);
                        }}
                      >
                        <ClipboardList size={16} />
                        Generate response plan
                      </Button>
                    )}
                    {latest?.assignments.length ? (
                      <>
                        <h3>
                          {latest.approved_at
                            ? "Assigned resources"
                            : "Proposed resources"}
                        </h3>
                        {latest.assignments.map((assignment) => (
                          <div className="evidence" key={assignment.id}>
                            <strong>{assignment.vehicle.call_sign}</strong>
                            <p>
                              <ArrowRight size={13} />{" "}
                              {assignment.hospital?.name || "On-scene support"}{" "}
                              · {assignment.patients} patient(s)
                            </p>
                          </div>
                        ))}
                      </>
                    ) : null}
                    {action.feedback}
                  </>
                )}
                {tab === "Reports" &&
                  item.reports.map((report) => (
                    <article className="evidence" key={report.id}>
                      <div className="row">
                        <Badge value={report.status} />
                        <small>{time(report.observed_at)}</small>
                      </div>
                      <p>{report.description}</p>
                      <p>
                        Reported injured:{" "}
                        {report.reported_casualties ?? "Unknown"}
                      </p>
                      <small className="muted">
                        Source: {report.source} · {report.id.slice(0, 8)}
                      </small>
                      {report.photo && (
                        <a
                          href={report.photo}
                          target="_blank"
                          rel="noreferrer"
                          className="text-link"
                        >
                          View attached photo
                        </a>
                      )}
                    </article>
                  ))}
                {tab === "History" && (
                  <>
                    {item.history.map((event) => (
                      <article className="evidence" key={event.id}>
                        <small>
                          {time(event.created_at)} ·{" "}
                          {event.action.replaceAll("_", " ")}
                        </small>
                        <p>{event.details}</p>
                      </article>
                    ))}
                    {!item.history.length && (
                      <Empty>No coordinator decisions recorded yet.</Empty>
                    )}
                  </>
                )}
              </div>
            </>
          )
        )}
      </Drawer>
      <PlanDetail id={planId} onClose={() => setPlanId(null)} />
    </>
  );
}
