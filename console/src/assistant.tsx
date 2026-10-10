import { ArrowUp, Bot, Check, Flag, Mail, PanelLeftClose, Paperclip, Reply, Sparkles, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import {
  CallError,
  LoadError,
  applyCompanyField,
  applyLeadChange,
  askAssistant,
  interpretCompanyField,
  interpretLeadChange,
  reviewPlaybook,
  setPlaybookText,
  type Answer,
} from "./api";
import { NAME } from "./brand";
import { href, leadHref } from "./router";
import type { CompanyFieldProposal, LeadChatProposal } from "./types";

export interface Said {
  from: "you" | "assistant";
  text: string;
  refused?: boolean;
  link?: Answer["link"];
  leads?: { id: string; company: string }[];
}

const OPENERS: [string, string, typeof Flag][] = [
  ["What needs me today?", "needs", Flag],
  ["What is waiting in my drafts?", "drafts", Mail],
  ["Has anyone replied?", "replied", Reply],
];

/** Where a page the assistant points at lives. */
function linkTo(link: NonNullable<Answer["link"]>): string {
  if (link.page === "lead") return leadHref(link.lead_id);
  if (link.page === "leads") return href("/leads", link.show ? { show: link.show } : {});
  if (link.page === "dashboard") return href("/");
  return href(`/${link.page}`);
}

/** The read-only statuses the lead interpreter returns that are not an actionable proposal; each maps
 *  to a plain message the assistant says back (no model, no guessing). */
function nonActionableMessage(p: LeadChatProposal): string | null {
  if (p.status === "need_more") {
    return p.reason === "unstorable"
      ? `This sheet has no column for: ${(p.columns ?? []).join(", ")}.`
      : "To add a lead I need a company and at least one of email, phone or website.";
  }
  if (p.status === "bad_email") return `That email does not look valid: ${p.value}. Nothing was changed.`;
  if (p.status === "no_lead") return `There is no lead ${p.lead_id}. Check the Lead ID.`;
  if (p.status === "protected") {
    return `A lead's own columns are protected and not changed here: ${(p.columns ?? []).join(", ")}. ` +
      "You can set its system fields (fit, profile, email check, evidence) by note, but edit its " +
      "company/email/website in the Sheet.";
  }
  return null;
}

export function Assistant(props: {
  companies: Map<string, string>;
  onClose: () => void;
  canWrite?: boolean;
  companyNextField?: string | null;
  companyNextLabel?: string | null;
  onChanged?: () => void;
  ask?: typeof askAssistant;
  interpret?: typeof interpretLeadChange;
  apply?: typeof applyLeadChange;
  interpretCompany?: typeof interpretCompanyField;
  applyCompany?: typeof applyCompanyField;
  review?: typeof reviewPlaybook;
  savePlaybook?: typeof setPlaybookText;
}) {
  const [said, setSaid] = useState<Said[]>([]);
  const [pending, setPending] = useState<LeadChatProposal | null>(null);
  const [pendingCompany, setPendingCompany] = useState<CompanyFieldProposal | null>(null);
  const [playbook, setPlaybook] = useState<{ text: string; name: string; summary: string } | null>(null);
  const [question, setQuestion] = useState("");
  const [thinking, setThinking] = useState(false);
  const [busy, setBusy] = useState(false);
  const thread = useRef<HTMLDivElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const ask = props.ask ?? askAssistant;
  const interpret = props.interpret ?? interpretLeadChange;
  const apply = props.apply ?? applyLeadChange;
  const interpretCompany = props.interpretCompany ?? interpretCompanyField;
  const applyCompany = props.applyCompany ?? applyCompanyField;
  const review = props.review ?? reviewPlaybook;
  const savePlaybook = props.savePlaybook ?? setPlaybookText;

  useEffect(() => {
    thread.current?.scrollTo?.({ top: thread.current.scrollHeight });
  }, [said, thinking, pending, pendingCompany]);

  const add = (line: Said) => setSaid((before) => [...before, line]);

  function answer(asked: string) {
    ask(asked).then(
      (a) =>
        add({
          from: "assistant", text: a.answer, refused: a.refused, link: a.link,
          leads: (a.lead_ids ?? []).map((id) => ({ id, company: props.companies.get(id) ?? id })),
        }),
      (error: unknown) =>
        add({ from: "assistant", refused: true, text: error instanceof LoadError ? error.message : "I could not answer just now." }),
    ).finally(() => setThinking(false));
  }

  const put = (text: string) => {
    const asked = text.trim();
    if (!asked || thinking || busy) return;
    add({ from: "you", text: asked });
    setQuestion("");
    setPending(null);
    setPendingCompany(null);
    setThinking(true);
    // When writing is on, read the instruction first (deterministic, no model): a recognised lead
    // action, else a recognised company-info answer, else it was a question to answer.
    if (props.canWrite) {
      interpret(asked).then(
        (p) => {
          if (p.status === "ready") {
            setPending(p);
            setThinking(false);
            return;
          }
          const message = nonActionableMessage(p);
          if (message) {
            add({ from: "assistant", text: message });
            setThinking(false);
            return;
          }
          interpretCompany(asked).then(
            (cp) => {
              if (cp.status === "ready") {
                setPendingCompany(cp);
              } else if (cp.status === "invalid") {
                add({ from: "assistant", text: `For ${cp.label}: ${cp.reason}. Nothing was changed.` });
              } else {
                answer(asked); // "unclear" from both -> it was a question
                return;
              }
              setThinking(false);
            },
            () => answer(asked),
          );
        },
        () => answer(asked),
      );
    } else {
      answer(asked);
    }
  };

  function confirm(p: LeadChatProposal) {
    if (busy || p.status !== "ready" || !p.op || !p.fields) return;
    setBusy(true);
    apply({ op: p.op, lead_id: p.lead_id, fields: p.fields }).then(
      (result) => {
        setBusy(false);
        setPending(null);
        add({ from: "assistant", text: p.op === "add" ? `Added ${result.lead_id || "the lead"}.` : `Updated ${result.lead_id}.` });
        props.onChanged?.();
      },
      (error: unknown) => {
        setBusy(false); // keep the proposal so the founder can retry or cancel
        add({ from: "assistant", refused: true, text: error instanceof CallError ? error.message : "The change could not be saved." });
      },
    );
  }

  function confirmCompany() {
    if (busy || pendingCompany?.status !== "ready" || !pendingCompany.field) return;
    const { field, label, value } = pendingCompany;
    setBusy(true);
    applyCompany(field, value ?? "").then(
      (result) => {
        setBusy(false);
        setPendingCompany(null);
        const next = result.next_label ? ` Next, what's ${result.next_label}?` : " That's everything I need about your company.";
        add({ from: "assistant", text: `Saved ${label}.${next}` });
        props.onChanged?.();
      },
      (error: unknown) => {
        setBusy(false); // keep the proposal so the founder can retry or cancel
        add({ from: "assistant", refused: true, text: error instanceof CallError ? error.message : "That could not be saved." });
      },
    );
  }

  function onFile(file: File | undefined | null) {
    if (!file || busy) return;
    add({ from: "you", text: `Playbook: ${file.name}` });
    setBusy(true);
    setPending(null);
    setPlaybook(null);
    review(file).then(
      (r) => {
        const words = r.text.trim().split(/\s+/).filter(Boolean).length;
        const hasFollowups = r.review.follow_ups && Object.values(r.review.follow_ups).some((f) => f.present);
        const parts = [r.review.initial_email?.present ? "an initial email" : "", hasFollowups ? "follow-ups" : ""].filter(Boolean);
        const seen = parts.length ? `, with ${parts.join(" and ")}` : "";
        setPlaybook({
          text: r.text,
          name: file.name,
          summary: `I read ${file.name} (${words} words${seen}). Save it as your live playbook? New drafts will be written from it.`,
        });
        setBusy(false);
      },
      (error: unknown) => {
        setBusy(false);
        add({ from: "assistant", refused: true, text: error instanceof CallError ? error.message : "That file could not be read." });
      },
    );
  }

  function confirmPlaybook() {
    if (!playbook || busy) return;
    setBusy(true);
    savePlaybook(playbook.text, playbook.name).then(
      () => {
        setBusy(false);
        setPlaybook(null);
        add({ from: "assistant", text: "Saved. New drafts will be written from this playbook." });
        props.onChanged?.();
      },
      (error: unknown) => {
        setBusy(false); // keep the proposal so the founder can retry or cancel
        add({ from: "assistant", refused: true, text: error instanceof CallError ? error.message : "The playbook could not be saved." });
      },
    );
  }

  const blurb = props.canWrite
    ? "Ask about your leads and drafts, tell me to add or update a lead, tell me your company info (name, email, website, address…), or attach a playbook (PDF or DOCX). I show what will change and you confirm before anything is written. I never send email."
    : "Ask about your leads, your drafts and what needs you. I read your Sheet and answer only from it; I cannot send or change anything.";

  return (
    <aside className="assistant" aria-label="Assistant">
      <div className="assistant-top">
        <span className="assistant-name">
          <Sparkles size={15} aria-hidden="true" /> Ask {NAME}
        </span>
        <button type="button" className="icon-button" onClick={props.onClose} aria-label="Hide the assistant">
          <PanelLeftClose size={17} aria-hidden="true" />
        </button>
      </div>

      <div className="thread" ref={thread}>
        {said.length === 0 && !pending && !pendingCompany ? (
          <div className="opening">
            <span className="assistant-mark" aria-hidden="true">
              <Bot size={22} />
            </span>
            <h2>How can I help?</h2>
            <p className="muted small">{blurb}</p>
            {props.canWrite && props.companyNextField && (
              <p className="muted small company-nudge">
                I still need {props.companyNextLabel} to finish your sender details — just type it below.
              </p>
            )}
            <div className="openers">
              {OPENERS.map(([text, key, Icon]) => (
                <button type="button" key={key} className="opener" onClick={() => put(text)}>
                  <Icon size={15} aria-hidden="true" />
                  {text}
                </button>
              ))}
            </div>
          </div>
        ) : (
          said.map((line, index) => (
            <div key={index} className={`bubble ${line.from}${line.refused ? " refused" : ""}`}>
              <p>{line.text}</p>
              {line.leads && line.leads.length > 0 && (
                <ul className="bubble-leads">
                  {line.leads.slice(0, 6).map((lead) => (
                    <li key={lead.id}>
                      <a href={leadHref(lead.id)}>{lead.company}</a>
                    </li>
                  ))}
                </ul>
              )}
              {line.link && (
                <a className="bubble-link" href={linkTo(line.link)}>
                  {line.link.label}
                </a>
              )}
            </div>
          ))
        )}

        {pending?.status === "ready" && pending.fields && (
          <div className="bubble assistant proposal">
            <p className="strong">
              {pending.op === "add" ? "Add a new lead?" : `Update ${pending.lead_id}?`}
              {pending.op === "update" && pending.company ? ` (${pending.company})` : ""}
            </p>
            <dl className="facts">
              {Object.entries(pending.fields).map(([field, value]) => (
                <div className="pair" key={field}>
                  <dt>{field}</dt>
                  <dd>{value}</dd>
                </div>
              ))}
            </dl>
            <div className="email-actions">
              <button type="button" className="primary" disabled={busy} onClick={() => confirm(pending)}>
                <Check size={15} aria-hidden="true" /> {busy ? "Saving…" : "Confirm"}
              </button>
              <button type="button" className="secondary" disabled={busy} onClick={() => setPending(null)}>
                <X size={15} aria-hidden="true" /> Cancel
              </button>
            </div>
          </div>
        )}

        {pendingCompany?.status === "ready" && (
          <div className="bubble assistant proposal">
            <p className="strong">
              Set {pendingCompany.label} to "{pendingCompany.value}"?
            </p>
            <div className="email-actions">
              <button type="button" className="primary" disabled={busy} onClick={confirmCompany}>
                <Check size={15} aria-hidden="true" /> {busy ? "Saving…" : "Confirm"}
              </button>
              <button type="button" className="secondary" disabled={busy} onClick={() => setPendingCompany(null)}>
                <X size={15} aria-hidden="true" /> Cancel
              </button>
            </div>
          </div>
        )}

        {playbook && (
          <div className="bubble assistant proposal">
            <p className="strong">Set your playbook?</p>
            <p className="small">{playbook.summary}</p>
            <div className="email-actions">
              <button type="button" className="primary" disabled={busy} onClick={confirmPlaybook}>
                <Check size={15} aria-hidden="true" /> {busy ? "Saving…" : "Save as my playbook"}
              </button>
              <button type="button" className="secondary" disabled={busy} onClick={() => setPlaybook(null)}>
                <X size={15} aria-hidden="true" /> Cancel
              </button>
            </div>
          </div>
        )}

        {thinking && (
          <p className="muted small thinking" role="status">
            Reading your Sheet…
          </p>
        )}
      </div>

      <form
        className="asking"
        onSubmit={(event) => {
          event.preventDefault();
          put(question);
        }}
      >
        <textarea
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              put(question);
            }
          }}
          placeholder={props.canWrite ? "Ask about leads, or add/update a lead…" : "Ask about your leads, drafts or replies…"}
          aria-label="Ask the assistant"
          rows={2}
          maxLength={400}
        />
        {props.canWrite && (
          <>
            <input
              ref={fileInput}
              type="file"
              accept=".pdf,.docx"
              style={{ display: "none" }}
              onChange={(event) => {
                onFile(event.target.files?.[0]);
                event.target.value = ""; // allow re-selecting the same file
              }}
            />
            <button
              type="button"
              className="round"
              disabled={thinking || busy}
              aria-label="Attach a playbook (PDF or DOCX)"
              title="Attach a playbook (PDF or DOCX)"
              onClick={() => fileInput.current?.click()}
            >
              <Paperclip size={17} aria-hidden="true" />
            </button>
          </>
        )}
        <button type="submit" className="round" disabled={thinking || busy || !question.trim()} aria-label="Ask">
          <ArrowUp size={17} aria-hidden="true" />
        </button>
      </form>
    </aside>
  );
}
