import { ArrowUp, Bot, Flag, Mail, PanelLeftClose, Reply, Sparkles } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { LoadError, askAssistant, type Answer } from "./api";
import { NAME } from "./brand";
import { href, leadHref } from "./router";

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

export function Assistant(props: {
  companies: Map<string, string>;
  onClose: () => void;
  ask?: typeof askAssistant;
}) {
  const [said, setSaid] = useState<Said[]>([]);
  const [question, setQuestion] = useState("");
  const [thinking, setThinking] = useState(false);
  const thread = useRef<HTMLDivElement>(null);
  const ask = props.ask ?? askAssistant;

  useEffect(() => {
    thread.current?.scrollTo?.({ top: thread.current.scrollHeight });
  }, [said, thinking]);

  const put = (text: string) => {
    const asked = text.trim();
    if (!asked || thinking) return;
    setSaid((before) => [...before, { from: "you", text: asked }]);
    setQuestion("");
    setThinking(true);
    ask(asked).then(
      (answer) =>
        setSaid((before) => [
          ...before,
          {
            from: "assistant",
            text: answer.answer,
            refused: answer.refused,
            link: answer.link,
            leads: (answer.lead_ids ?? []).map((id) => ({ id, company: props.companies.get(id) ?? id })),
          },
        ]),
      (error: unknown) =>
        setSaid((before) => [
          ...before,
          {
            from: "assistant",
            refused: true,
            text: error instanceof LoadError ? error.message : "I could not answer just now.",
          },
        ]),
    ).finally(() => setThinking(false));
  };

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
        {said.length === 0 ? (
          <div className="opening">
            <span className="assistant-mark" aria-hidden="true">
              <Bot size={22} />
            </span>
            <h2>How can I help?</h2>
            <p className="muted small">
              Ask about your leads, your drafts and what needs you. I read your Sheet and answer only
              from it; I cannot send or change anything.
            </p>
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
          placeholder="Ask about your leads, drafts or replies…"
          aria-label="Ask the assistant"
          rows={2}
          maxLength={400}
        />
        <button type="submit" className="round" disabled={thinking || !question.trim()} aria-label="Ask">
          <ArrowUp size={17} aria-hidden="true" />
        </button>
      </form>
    </aside>
  );
}
