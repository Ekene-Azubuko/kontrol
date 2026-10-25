import type { ResponsePlan } from "@/lib/response-types";
import {
  hospitalOptions,
  reviewAlerts,
  reviewChecks,
  uniqueNotes,
} from "@/lib/plan-review";

/** Surface concise review facts and unmet requirements while retaining every distinct constraint on demand. */
export function PlanReviewChecks({ plan }: { plan: ResponsePlan }) {
  const checks = reviewChecks(plan, hospitalOptions(plan));
  const alerts = reviewAlerts(plan);
  const notes = uniqueNotes(plan.constraints);
  return (
    <section className="plan-review-checks" aria-label="Quick review checks">
      <h3>Quick review checks</h3>
      <div className="review-check-grid">
        {checks.map((check) => (
          <div key={check.label} className={check.attention ? "attention" : ""}>
            <small>{check.label}</small>
            <strong>{check.value}</strong>
          </div>
        ))}
      </div>
      {plan.status === "needs_information" && (
        <p className="review-attention">
          Unresolved constraints require dispatcher review.
        </p>
      )}
      {!!alerts.length && (
        <div className="review-alerts" role="status">
          <strong>Unmet requirements & resource conflicts</strong>
          <ul>
            {alerts.map((alert) => (
              <li key={alert}>{alert}</li>
            ))}
          </ul>
        </div>
      )}
      {!!notes.length && (
        <details className="review-full-notes">
          <summary>Full constraints & considerations ({notes.length})</summary>
          <ul>
            {notes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}
