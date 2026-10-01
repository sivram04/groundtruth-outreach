import { FlaskConical, Users } from "lucide-react";
import { useState } from "react";
import { ExperimentError, assignExperiment, defineExperiment } from "../api";
import { Card, PageHead, SectionHead, Status } from "../components";
import type { ExperimentReport, ExperimentVariant, Snapshot, VariantMetric } from "../types";

/** Define two named variants, assign eligible leads to them, and read the variant-level report.
 *  READ-ONLY beyond those two writes: a variant is a NAME only — it carries no outreach copy and is
 *  not connected to drafting, so choosing it changes no email. An assignment is deterministic and
 *  immutable: a refresh, a retry or a follow-up can never move a lead between variants.
 *  `define`/`assign` are injectable for tests. */
export function Experiments({
  data,
  onChanged,
  define = defineExperiment,
  assign = assignExperiment,
}: {
  data: Snapshot;
  onChanged?: () => void;
  define?: typeof defineExperiment;
  assign?: typeof assignExperiment;
}) {
  const report = data.experiments ?? null;
  const [name, setName] = useState(report?.name ?? "");
  const [variantA, setVariantA] = useState(report?.variants?.[0]?.name ?? "");
  const [variantB, setVariantB] = useState(report?.variants?.[1]?.name ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [said, setSaid] = useState("");

  function run(work: () => Promise<string>) {
    if (busy) return;
    setBusy(true);
    setError("");
    setSaid("");
    work().then(
      (message) => {
        setBusy(false);
        setSaid(message);
        onChanged?.();
      },
      (e: unknown) => {
        setBusy(false);
        setError(e instanceof ExperimentError ? e.message : "That could not be saved.");
      },
    );
  }

  const onDefine = () =>
    run(async () => {
      const result = await define({ experiment: name.trim(), variant_a: variantA.trim(), variant_b: variantB.trim() });
      return result.written > 0
        ? `Saved “${result.name}”: ${result.variants.join(" vs ")}.`
        : "That experiment was already defined with those variants.";
    });

  const onAssign = () =>
    run(async () => {
      const result = await assign({ experiment: (report?.name || name).trim() });
      return `${result.assigned} newly assigned; ${result.already_assigned} already assigned; ${result.ineligible} not eligible.`;
    });

  const canDefine = Boolean(name.trim() && variantA.trim() && variantB.trim() && variantA.trim() !== variantB.trim());
  const canAssign = Boolean(report?.defined || (name.trim() && report));

  return (
    <>
      <PageHead
        title="A/B tests"
        sub="Two named variants and a stable assignment per lead. Until a variant's content changes a draft and that exposure is recorded, this shows observed activity by assigned group, not A/B performance."
      />

      <Card title="Define the experiment" icon={FlaskConical}>
        <p className="small muted">
          Name the test and its two variants. A variant is a name only: it is not connected to drafting and
          changes no email. Defining the same thing again saves nothing new.
        </p>
        <div className="import-controls">
          <label className="small">
            Experiment{" "}
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Subject line test" maxLength={80} />
          </label>
          <label className="small">
            Variant A{" "}
            <input value={variantA} onChange={(e) => setVariantA(e.target.value)} placeholder="Short subject" maxLength={80} />
          </label>
          <label className="small">
            Variant B{" "}
            <input value={variantB} onChange={(e) => setVariantB(e.target.value)} placeholder="Long subject" maxLength={80} />
          </label>
          <button type="button" className="primary" disabled={busy || !canDefine} onClick={onDefine}>
            Save the variants
          </button>
        </div>
      </Card>

      <Card title="Assign eligible leads" icon={Users}>
        <p className="small muted">
          Every emailable, qualified lead that is not already assigned is placed in a variant. The variant is
          decided by a fixed rule from the lead’s id, so it is the same on every run; a lead already assigned
          is never moved.
        </p>
        <button type="button" className="primary" disabled={busy || !canAssign} onClick={onAssign}>
          Assign eligible leads
        </button>
        {!report?.defined && <p className="small muted">Define the two variants first.</p>}
      </Card>

      {busy && <p className="small muted loading">Saving…</p>}
      {error && (
        <div className="callout amber" role="alert">
          <div className="callout-text">{error}</div>
        </div>
      )}
      {said && (
        <div className="callout blue" role="status">
          <div className="callout-text">{said}</div>
        </div>
      )}

      {data.experiments_unreadable && (
        <div className="callout amber" role="alert">
          <div className="callout-text">The A/B tests tab could not be read, so no report is shown.</div>
        </div>
      )}

      {report && report.variants.some((v) => v.assigned > 0) && <Report report={report} />}
    </>
  );
}

function cell(metric: VariantMetric | undefined) {
  if (!metric) return <span className="muted">—</span>;
  if (!metric.available)
    return (
      <span className="muted" title={metric.why}>
        not available
      </span>
    );
  const denom =
    metric.key === "assigned" || !metric.denominator_label
      ? null
      : ` · ${metric.rate} of ${metric.denominator} ${metric.denominator_label}`;
  return (
    <>
      <span className="strong">{metric.count}</span>
      {metric.estimate && <span className="muted small"> (est.)</span>}
      {denom && <span className="muted small">{denom}</span>}
    </>
  );
}

function Report({ report }: { report: ExperimentReport }) {
  const a = report.variants[0];
  const b = report.variants[1];
  if (!a || !b) return null;
  const keys = a.metrics.map((m) => m.key);
  const label = (variant: ExperimentVariant) => variant.name || `Variant ${variant.index + 1}`;
  const byKey = (variant: ExperimentVariant, key: string) => variant.metrics.find((m) => m.key === key);
  return (
    <Card title="Observed activity by assigned group" icon={FlaskConical}>
      <SectionHead title={report.name}>
        <Status tone="gray">Not A/B performance</Status>
      </SectionHead>
      <div className="callout blue">
        <div className="callout-text small">{report.comparison.note}</div>
      </div>
      <div className="card flush scroll">
        <table className="leads-table">
          <thead>
            <tr>
              <th scope="col">Metric</th>
              <th scope="col">{label(a)}</th>
              <th scope="col">{label(b)}</th>
            </tr>
          </thead>
          <tbody>
            {keys.map((key) => (
              <tr key={key}>
                <th scope="row" className="small">
                  {byKey(a, key)?.label}
                  {byKey(a, key)?.note && <span className="muted small block">{byKey(a, key)?.note}</span>}
                </th>
                <td className="small">{cell(byKey(a, key))}</td>
                <td className="small">{cell(byKey(b, key))}</td>
              </tr>
            ))}
            {report.variants.some((v) => v.suppressed) && (
              <tr>
                <th scope="row" className="small">
                  Assigned, now suppressed
                  <span className="muted small block">still counted as assigned; shown for context</span>
                </th>
                <td className="small">{a.suppressed ?? "—"}</td>
                <td className="small">{b.suppressed ?? "—"}</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <ul className="small muted">
        {report.notes.map((note, i) => (
          <li key={i}>{note}</li>
        ))}
      </ul>
    </Card>
  );
}
