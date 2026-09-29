import { Card, DraftingSettings } from "../components";
import { leadHref } from "../router";
import type { Snapshot } from "../types";

export function Drafts({ data }: { data: Snapshot }) {
  const leads = new Map(data.leads.map((lead) => [lead.id, lead]));
  const ready = data.ready?.map((id) => leads.get(id)).filter((lead) => lead !== undefined) ?? null;
  return (
    <>
      <h1>Drafts</h1>
      <p className="note">
        Here you will open each draft, change it if you want, and press Approve, which sends that one email. That comes
        next: for now this page only shows.
      </p>

      {data.drafts.length > 0 ? (
        <Card title="Drafts in Gmail">
          <div className="scroll">
            <table>
              <thead>
                <tr>
                  <th scope="col">Lead</th>
                  <th scope="col">Company</th>
                  <th scope="col">Email</th>
                  <th scope="col">Status</th>
                  <th scope="col">Made</th>
                  <th scope="col">Tracked</th>
                </tr>
              </thead>
              <tbody>
                {data.drafts.map((draft) => (
                  <tr key={`${draft.lead_id}-${draft.kind}`}>
                    <td>
                      <a href={leadHref(draft.lead_id)}>{draft.lead_id}</a>
                    </td>
                    <td>{leads.get(draft.lead_id)?.company}</td>
                    <td>{draft.kind}</td>
                    <td>{draft.status === "CREATED" ? "In Gmail" : "Not confirmed by Gmail"}</td>
                    <td className="nowrap">{draft.at}</td>
                    <td>{draft.tracked ? "yes" : "no"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      ) : (
        <Card className="empty">
          <h2>No drafts yet</h2>
          <p className="muted">No first email or follow-up has been drafted. What drafting waits for is below.</p>
        </Card>
      )}

      <Card title="What drafting waits for">
        <DraftingSettings approvals={data.approvals} />
      </Card>

      <Card title={`Ready for a first draft${ready ? `: ${ready.length}` : ""}`}>
        <p className="muted small">
          Email checked OK, company qualified and profiled, never emailed, not on hold or suppressed, and no draft yet. A
          draft also needs a usable quote about the company, which is judged when the draft is written.
        </p>
        {ready === null ? (
          <p className="warn">This cannot be told: the Suppression tab cannot be read.</p>
        ) : ready.length === 0 ? (
          <p className="muted">No lead is ready.</p>
        ) : (
          <div className="scroll">
            <table>
              <thead>
                <tr>
                  <th scope="col">Lead</th>
                  <th scope="col">Company</th>
                  <th scope="col">Contact</th>
                  <th scope="col">Email</th>
                  <th scope="col">Tier</th>
                </tr>
              </thead>
              <tbody>
                {ready.map((lead) => (
                  <tr key={lead.id}>
                    <td>
                      <a href={leadHref(lead.id)}>{lead.id}</a>
                    </td>
                    <td>{lead.company}</td>
                    <td>{lead.contact}</td>
                    <td>{lead.email}</td>
                    <td>{lead.tier_label}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}
