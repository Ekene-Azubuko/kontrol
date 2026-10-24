"use client";
import { useState } from "react";
import { Bot, ChevronRight, Clock3, RotateCcw } from "lucide-react";
import { useData } from "@/lib/api";
import { branding } from "@/lib/branding";
import type { AgentRun } from "@/lib/types";
import { Badge, Empty, ErrorBox, Panel, useAction } from "./shared";
import { PageHeading } from "./page-heading";
import { Drawer } from "./ui/dialog";
import { Button } from "./ui/button";
import { stages, Workflow } from "./response-plans";
import { time } from "@/lib/utils";

/** Expose persisted stage inputs, structured outputs, failures and bounded retries. */
export function AgentWorkspace() {
  const runs = useData<AgentRun[]>("/agents");
  const [selected, setSelected] = useState<string | null>(null);
  const [filter, setFilter] = useState("all");
  const action = useAction();
  const currentRuns = runs.data?.filter((item) => item.plan_id) || [];
  const run = runs.data?.find((item) => item.id === selected);
  return (
    <>
      <PageHeading
        eyebrow="AGENT OBSERVABILITY"
        title={branding.agents}
        subtitle="Actual execution state, source evidence, and structured findings. Agents advise; coordinators decide."
      />
      <Panel title="Intake → parallel evaluation → planning → approval">
        <div className="workflow-container">
          <Workflow
            runs={currentRuns.filter(
              (r) => r.plan_id === currentRuns[0]?.plan_id,
            )}
          />
        </div>
      </Panel>
      <div className="agent-cards response-agents">
        {stages.map(({ key: stage, name, description }, index) => {
          const stageRuns =
            currentRuns.filter((item) => item.stage === stage) || [];
          return (
            <div className="panel agent-card" key={stage}>
              <div className="row">
                <span className="agent-icon">
                  <Bot size={24} />
                </span>
                <span className="mono">0{index + 1}</span>
              </div>
              <h2>{name} Agent</h2>
              <p>{description}</p>
              <div className="row">
                <Badge
                  value={
                    stageRuns.some((item) => item.status === "running")
                      ? "running"
                      : "idle"
                  }
                />
                <small>
                  {
                    stageRuns.filter((item) => item.status === "completed")
                      .length
                  }{" "}
                  completed
                </small>
              </div>
            </div>
          );
        })}
      </div>
      <Panel
        title="Execution log"
        action={
          <select
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
            aria-label="Filter agent runs"
          >
            <option value="all">All statuses</option>
            {["queued", "running", "completed", "failed"].map((value) => (
              <option key={value}>{value}</option>
            ))}
          </select>
        }
      >
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Run</th>
                <th>Agent</th>
                <th>Status</th>
                <th>Started</th>
                <th>Duration</th>
                <th>Attempts</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {currentRuns
                .filter((item) => filter === "all" || item.status === filter)
                .map((item) => (
                  <tr key={item.id} onClick={() => setSelected(item.id)}>
                    <td>
                      <button
                        className="table-title mono"
                        onClick={() => setSelected(item.id)}
                      >
                        {item.id.slice(0, 8)}
                      </button>
                    </td>
                    <td>
                      {item.stage}
                      <small>
                        {item.output?.summary || item.output?.plan_summary || item.output?.reasoning || "Awaiting validated output"}
                      </small>
                    </td>
                    <td>
                      <Badge value={item.status} />
                    </td>
                    <td>{time(item.started_at)}</td>
                    <td>
                      {item.completed_at && item.started_at
                        ? `${Math.max(0, (Date.parse(item.completed_at) - Date.parse(item.started_at)) / 1000).toFixed(2)}s`
                        : "—"}
                    </td>
                    <td>{item.attempts}</td>
                    <td>
                      <ChevronRight size={16} />
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
        {!runs.data?.length && (
          <Empty>Agent executions appear after a report is submitted.</Empty>
        )}
        {runs.error && <ErrorBox message={runs.error.message} />}
      </Panel>
      <Drawer
        open={!!run}
        onClose={() => setSelected(null)}
        title="Execution details"
      >
        {run && (
          <div className="detail-section">
            <div className="row">
              <h2>Incident {run.stage}</h2>
              <Badge value={run.status} />
            </div>
            <p className="mono">{run.id}</p>
            <div className="callout">
              <Clock3 size={16} />
              Started {time(run.started_at)} · Completed{" "}
              {time(run.completed_at)} · Attempt {run.attempts}/3
            </div>
            {run.error && <ErrorBox message={run.error} />}
            {run.status === "failed" && (
              <Button
                disabled={action.busy || run.attempts >= 3}
                onClick={() =>
                  action.act(
                    `/agents/${run.id}/retry`,
                    {},
                    "POST",
                    "Execution queued for retry",
                  )
                }
              >
                <RotateCcw size={15} />
                Retry failed stage
              </Button>
            )}
            {action.feedback}
            <h3>Input summary</h3>
            <p>
              {String(
                (run.input.agent_input as { description?: string } | undefined)
                  ?.description ||
                  "Input will be captured when execution begins.",
              )}
            </p>
            <h3>Output summary</h3>
            <p>{run.output?.summary || run.output?.plan_summary || run.output?.reasoning || "No output yet"}</p>
            <h3>Input & source records</h3>
            <pre>{JSON.stringify(run.input, null, 2)}</pre>
            <h3>Structured output</h3>
            <pre>
              {run.output
                ? JSON.stringify(run.output, null, 2)
                : "No output yet. This execution has not completed."}
            </pre>
            {run.raw_response && (
              <>
                <h3>Raw CREAO response</h3>
                <pre>{JSON.stringify(run.raw_response, null, 2)}</pre>
              </>
            )}
          </div>
        )}
      </Drawer>
    </>
  );
}
