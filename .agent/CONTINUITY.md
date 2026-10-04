# Outreach continuity

## [PLANS]

- 2026-09-23T02:57Z [USER] Supersedes the local-handbook assumption below:
  before stage 3 begins, the founder will put the final outreach handbook in
  Google Drive. The private drafting worker will run in GCP and read it there.
  The handbook is not in Drive yet; no link or new sign-in is due now. Current
  local template code remains a disabled prototype, not the planned writer.

- 2026-09-22T20:24:00-04:00 [ASSUMPTION] Stage 3 proceeds locally: review four real
  company-profile previews after the founder fills the handbook, then a
  controlled Gmail-draft pilot. Stage 4 sent/reply sync and follow-ups are
  separate; bulk research and all schedules remain paused.

## [DECISIONS]

- 2026-09-28 [USER] Stage 4 decisions: threads the founder started by hand (the 14 of
  2026-09-22) get reminders in Next action, never follow-up drafts; business days skip weekends
  and the major US holidays (New Year's, Memorial Day, July 4, Labor Day, Thanksgiving and the
  day after, Christmas); follow-up wording is approved once per handbook version
  (`followup_approved_handbook_hash` = the Drive document's content hash).

- 2026-09-23T02:19Z [USER] Supersedes the generic "accounting and operational
  data" outreach phrasing below: name the actual inputs in prospective copy.
  The founder has not approved a replacement offer. [CODE] The product's
  founder-decided checklist in `docs/construction/CASH_FLOW_INPUTS_AND_DATA_SOURCES.md`
  names bank balances, open invoices and bills, payroll by pay date, fixed
  costs, upcoming billings by job, plus commitments, retainage and credit-line
  details when applicable. Use a concise, accurate subset in a cold email;
  do not imply current live integrations or a completed MVP.

- 2026-09-23T01:37Z [USER] Corrected the outreach positioning: Lakshyaa is an
  AI-powered cash-flow decision product for construction subcontractors. It is
  intended to combine accounting and operational data, analyze the company's
  situation, compare scenarios, and recommend next steps from that analysis.
  The prior "see cash needs" offer wording was rejected. Replacement wording
  is not yet founder-approved; do not present planned capabilities as live.

- 2026-09-22T20:24:00-04:00 [USER] The MVP is unfinished this week; outreach may
  invite next-week conversations but must not promise a live trial today.
- 2026-09-22T20:24:00-04:00 [USER] Asked Claude Code to build the missing automated
  drafting pipeline. [TOOL] Its local OAuth session was expired and could not
  refresh, so Codex continued the authorized local build.

## [PROGRESS]

- 2026-10-04 [CODE] MVP #6 in-thread draft create built. `reply.create(...)` + `POST /api/reply/<lead_id>/draft`
  turn the reviewed/edited reply into ONE real Gmail draft filed in the inbound reply's thread - draft only,
  never sent. Re-checks guards at the write boundary (STOP/suppression/no reply/no email), requires
  `ENABLE_GMAIL_DRAFTS=true` AND `enable_reply` (flag alone never writes), refuses a thread that already holds
  a draft, NO tracking on a reply (so a reply's opens never pollute initial metrics). Lead page has a "Create
  draft in Gmail" button. Offline: Python 1100, frontend 125 + tsc + build. NOT done: reply opens/clicks into
  metrics (out of scope - needs a tracking_job.actions extension), a live browser run. For the founder's LIVE
  tracking/metrics self-test use the EXISTING harness `outreach/tracking_check.py`
  (`ENABLE_GMAIL_DRAFTS=true python -m outreach.tracking_check --to you@otherinbox`): it drafts one tracked
  email to the founder's own other inbox (refuses any lead/suppressed/sender address), records a DRAFTED(test)
  event keyed `test:<action>` so `tracking_job` attributes the OPEN/CLICK. LIVE prerequisites to verify before
  running: ENABLE_GMAIL_DRAFTS, the `tracking-signing-key` secret, `sender_website` must be a lakshyaa.ai https
  link (only `lakshyaa.ai` is click-tracked; the open pixel works regardless), the tracker deployed/reachable
  at t.lakshyaa.ai, and `tracking_job.run` draining the hit queue into Events that the dashboard reads.

- 2026-10-04 [CODE] MVP #6 reply-draft candidate + booking link, wired onto the lead page. `outreach/reply.py`
  (pure, like `post_call.py`): after a lead writes back, a review-only suggested reply grounded in the recorded
  reply, the company's cited words and the approved offer; NEVER states what the reply said (inbound text is not
  parsed). Booking link = new settings key `booking_link` (real https only). Blocked by call STOP / suppression /
  no email / no offer / no handbook; opt-out/bounce/auto-reply give none; HOLD does not block. Route
  `GET /api/reply/<lead_id>/candidate` (flag `enable_reply`, OFF by default and in deploy), reads only, fails
  closed on unreadable Events/Call log/Suppression/handbook. Frontend `ReplyCandidate.tsx` on the lead page.
  Offline-verified in network-disabled containers: Python 1090, frontend 123 + tsc + build. NOT done: in-thread
  Gmail draft create from the candidate (review-gated, later), a browser run against the live API, and the
  founder's real booking URL. Tests cover each guard; no full deliberate-break sweep this increment. Nothing
  deployed, nothing sent. Separately, a live read-only probe confirmed the founder token works (scopes:
  gmail.compose, gmail.readonly, spreadsheets, drive.readonly) -> drive.readonly means the test handbook must be
  created by the founder, not the agent; the live Sheet has no Call log or A/B tab yet.

- 2026-09-28 [CODE] Stage 4 built locally: `outreach/sync.py` (Gmail read-only -> Events,
  Suppression, lead summary columns), `outreach/followup.py` (the handbook's own follow-up
  wording, drafted in the original thread), `mailbox.py`, `sequence.py`, `business_days.py`.
  390 tests pass offline in the container; 62/62 deliberate breaks caught. Not deployed, not
  scheduled, never run against the live mailbox or Sheet. Next: a read-only `sync --dry-run`
  on the real mailbox, with the founder's go.

- 2026-09-23T03:39Z [CODE] Stage 3 local audit closed the fixed-template Gmail-draft
  bypass: the live preview endpoint always uses the Drive writer, and `create` requires a
  written payload that is revalidated against the handbook. Added conservative polarity
  checks for quote negation and qualified product state. No deployment or remote write.

- 2026-09-22T20:48:00-04:00 [CODE] Local Stage 3 previews now list every current
  verified OFFERING/MARKET quote, allow an explicit quote ID bound to the
  approval hash, avoid weak automatic defaults, and use `Decision maker` for a
  first-name greeting only when `Their email` equals `BEST EMAIL` and is not a
  role inbox. No live write or deployment.

- 2026-09-22T20:24:00-04:00 [CODE] Local Stage 3 code now renders evidence-backed
  initial-email previews, requires exact date-bound hash approval, and has a
  disabled-by-default Gmail draft creation path with Sheets reservation and
  conservative reconciliation. No deployment or live Google write occurred.

## [DISCOVERIES]

- 2026-10-01 [FIX] A/B 3rd recheck (of 0e43645): tracked-open linkage. The 2nd recheck's thread-only rule
  excluded a real tracked open, because tracking_job.hit_event writes OPEN with Match "TRACKER", a BLANK
  Thread ID, and the draft action in Detail ("draft <action>") (repro: post-assignment tracked draft +
  sent + open => 1 sent, 0 opens, 1 unattributable). Fix in experiments._lead_signals: a tracker open is
  linked by DRAFT-ACTION evidence — the open's action (parsed from Detail) must name a post-assignment
  TRACKED INITIAL draft (action from the DRAFTED event key "draft:<action>"), and be after the qualifying
  send (existing send-time/preview rule). Thread-based outcomes (REPLIED/OPT_OUT/MEETING/POSITIVE/followup
  send) now require a NONEMPTY shared thread id (two blanks are not a link). tracked (opens denominator) =
  qualifying send exists AND had a post-assignment tracked initial draft. Added _draft_action() helper;
  THREAD_DOWNSTREAM constant; OPEN handled separately from thread events. No report-shape change => frontend
  untouched. Repro fixed through GET /api/snapshot: 1 sent, 1 open, 0 unattributable. Regressions:
  test_experiments.py (tracked-open-counted, open-no-qualifying, open-different-draft, reply-nonempty-thread)
  + test_console_experiments.py (tracked open through the real snapshot); test helpers drafted()/opened()
  build realistic tracker events (DRAFTED key draft:<action>; OPEN Match TRACKER, blank thread, Detail
  "draft <action>"). Verified no-network: Python 1060, frontend 117 + tsc/build; real loopback-HTTP
  confirmed. Committed only my code/tests + MVP_DELIVERY + evidence doc; AS_BUILT + CONTINUITY left
  UNCOMMITTED (another agent's entries). Variants still not connected to drafting.

- 2026-10-01 [FIX] A/B 2nd recheck (of 8493d7b): one more attribution case + a framing change. (1)
  DOWNSTREAM LINKAGE: a reply/opt-out/open/follow-up recorded AFTER assignment but to a send made BEFORE
  assignment was counted. A downstream email outcome now counts ONLY when it links to a QUALIFYING
  post-assignment send (earliest INITIAL confident send at/after assignment): same thread, after that send.
  experiments._lead_signals computes the qualifying send per lead (time + Thread ID) and attributes
  downstream outcomes to it; otherwise the event is a new exclusion kind `unattributable` (beside
  before_assignment, undated). DOWNSTREAM = REPLIED/OPT_OUT/OPEN/MEETING/POSITIVE_REPLY + FOLLOWUP sends.
  (2) OBSERVED ACTIVITY framing: report.basis="observed_activity"; comparison={winner:None, comparable:False,
  note "...not A/B performance...not comparable...reaching a number of sends would not make them
  comparable"}; removed can_compare/MIN_SENDS_TO_COMPARE (don't imply a send threshold => comparable).
  Console page retitled "Observed activity by assigned group" + "Not A/B performance" marker; types updated
  (comparison shape, basis, excluded.unattributable). Reproduced through GET /api/snapshot (send 09-30,
  assigned 10-01, reply 10-02 same thread => sent/replies 0, excluded before 1 + unattributable 1).
  Regressions: test_experiments.py (reply-to-pre-assignment-send, linked-reply counted, different-thread,
  followup-on-pre-assignment-thread, observed-activity) + test_console_experiments.py (reply case through
  the real snapshot) + Experiments.test.tsx (framing). Verified no-network: Python 1055, frontend 117 +
  tsc/build; real loopback-HTTP confirmed. Committed only my code/tests + MVP_DELIVERY + evidence doc;
  AS_BUILT + CONTINUITY left UNCOMMITTED (another agent's entries). Variants still not connected to drafting.

- 2026-10-01 [FIX] A/B recheck (of a2e427a): three correctness gaps closed, regressed through the real
  snapshot/API (docs/testing/experiments-2026-10-01.md "Recheck remediation"). (1) TIME-BASED ATTRIBUTION:
  outcomes before a lead's assignment were counted (reviewer's case: assigned Oct 1, send+reply Sep 30, both
  counted). experiments.read now keeps assigned_at; report/_lead_signals count an event/call ONLY when its
  time is reliably >= the assignment time; anything earlier, or undated, or with an unreadable assignment
  time, is NOT counted and is tallied excluded (variants[].excluded + report.excluded: before_assignment /
  undated) with a note. Covers previously-emailed leads (still assigned; old outcomes excluded). (2) CALLS
  UNAVAILABLE not 0 when the Call log is unreadable (available:false, no count). (3) ASSIGNMENT SAFETY:
  /api/experiments/assign now assigns only leads NOT suppressed and NOT in a call STOP/HOLD state
  (experiments.safe_to_assign reads suppression.covers + calls.outreach_effect); if the Suppression list OR
  the Call log is unreadable it refuses the whole assignment (502, nobody assigned — fail closed, an
  unreadable safety source is never permission). Regressions in test_experiments.py (23) +
  test_console_experiments.py (15) + Experiments.test.tsx (7). Verified no-network: Python 1050, frontend
  117 + tsc/build; real loopback-HTTP (previously-emailed lead → sent/replies totals 0, excluded 2, still
  assigned; unreadable suppression → 502). Committed only my code/tests + MVP_DELIVERY + the evidence doc;
  AS_BUILT + CONTINUITY updated in the working tree, left UNCOMMITTED (another agent's entries). Variants
  still not connected to drafting; nothing live/signed-in/deployed.

- 2026-10-01 [BUILD] A/B tests + variant-level reporting (MVP #9; local, flag-gated enable_experiments, OFF
  by default + deploy; docs/testing/experiments-2026-10-01.md). New pure outreach/experiments.py: the
  founder defines two named variants and assigns eligible leads; variant_index = sha256(experiment ∥
  lead_id) & 1 (deterministic, never random); ASSIGN Record ID = hash(experiment, lead_id) only, so a
  re-assign is the SAME row (skipped on append) and a lead can never be under two variants; read() takes the
  EARLIEST assignment and groups by a stable INDEX, so a rename changes only the label, never the lead.
  report() = every metric with an explicit denominator (assigned/drafted/confirmed-sent[≠delivery]/replies/
  opt-outs/calls/follow-up-emails-sent/opens[est.]); positive replies + meetings read "not available" (no
  recorded signal yet, not a misleading 0; recognised automatically if MEETING/POSITIVE_REPLY events ever
  appear); NO winner ever declared (MIN_SENDS_TO_COMPARE=30 flags small samples; above it still declines — a
  rate gap ≠ significance). Persistence: append-only "A/B tests" tab (sheet.py AB_TAB/AB_HEADER,
  Store.ab_records/append_ab_records, refuses changed columns, dedups by Record ID; MemoryStore mirrors).
  Routes POST /api/experiments/define + /assign under enable_experiments (a test keeps the default app's
  routes; _deployed doesn't pass the flag). console_model threads ab_records/experiments_enabled, adds each
  lead's variant/experiment/variant_index + the experiments report + experiments_unreadable. Frontend:
  Experiments.tsx page (define/assign + report with honest labels), nav+page gated by experiments_enabled,
  variant chip on Leads/Lead. NOT connected to drafting (variant = name only; no copy; no email changed;
  Drive handbook/offer untouched). Verified no-network: Python 1040 (13 + 8 new; demo snapshot.json
  regenerated — RW mount, not :ro), frontend 116 (6 new) + tsc/build; real loopback-HTTP through the real
  Flask + Store: define→assign (3 assigned, 2 ineligible, winner null, each lead carries its variant)→second
  assign moves nobody (byte-identical). Concurrency: AS_BUILT + this file hold another agent's uncommitted
  entries, so I committed only my code/tests + MVP_DELIVERY + the experiments evidence doc; AS_BUILT +
  CONTINUITY updated in the working tree, left UNCOMMITTED. NOT done: variant→drafting wiring (waits on
  handbook/offer), recording positive-reply/meeting signals, any live/signed-in run.

- 2026-10-01 [FIX] Playbook recheck follow-up (closes the 78e47e0 recheck's two gaps; docs/testing/
  playbook-2026-10-01.md "Remediation of the 78e47e0 recheck"). (1) Review ≠ selection: playbook_select.py
  now binds a purpose (REVIEW/SELECT) into the HMAC; /api/playbook/review mints a REVIEW token only (proof
  of review, NOT selection/approval); new POST /api/playbook/select verifies it and mints a SELECT token;
  /preview requires the SELECT token → a reviewed-but-never-selected version is refused (403), as are a
  review token at /preview, forged, changed text, other founder, expired. Non-durable (secret dies on
  restart), not wired to production drafting. Playbook.tsx: Select button calls selectPlaybook (a server
  step), selectionToken state, preview sends it. (2) Size bound BEFORE parsing: every route sets
  request.max_content_length = MAX_BYTES before request.files/get_json → 413 (too_large on /review), even
  with no usable Content-Length; /select & /preview also cap text at MAX_CHARS. Tests: test_playbook_select
  (purpose REVIEW≠SELECT), test_console_playbook (review→select→preview accepted; review-token-at-preview
  403; oversized multipart w/ and w/o Content-Length → 413; oversized select/preview JSON → 413). Verified
  no-network: Python 1019 (39 focused), frontend 110, tsc+build; real loopback-HTTP harness confirmed all
  seven boundaries. Durable selection recorded separately: docs/decisions/playbook-durable-selection-
  2026-10-01.md. Same concurrency note as below: AS_BUILT + this file carry another agent's uncommitted
  entries, so my commit is only my code/tests + MVP_DELIVERY + the playbook evidence doc + the decision
  note; AS_BUILT + CONTINUITY updated in the working tree but left UNCOMMITTED.

- 2026-10-01T19:13:31Z [TOOL] Independent recheck of 78e47e0: 32 focused Python
  and 4 Playbook frontend tests PASS in network-disabled containers. [CODE]
  Token proves review of exact text, but is minted before the founder's Select
  click; the API does not prove selection. Upload's bounded file read occurs
  after multipart parsing, with no route-level request-body limit. Evidence:
  docs/testing/playbook-2026-10-01.md. Local read-only scope; no product/live
  change in this recheck. [RESOLVED by the FIX above.]

- 2026-10-01 [FIX] Playbook preview boundary (recheck of 7f5d99b, docs/testing/playbook-2026-10-01.md). (1)
  Preview now needs VERIFIABLE selection evidence: new outreach/playbook_select.py mints an HMAC token
  (per-process secret) over content_hash|email|exp (30 min); /review returns it; /preview recomputes the
  hash from posted text + founder from session and 403s unless the token verifies → no bypass by posting
  arbitrary text+hash, changed text 403, other founder fails, dies on restart (local, time-bounded, NOT
  durable). (2) Size bounds before parsing: /review reads MAX_BYTES+1 (5MB) then 422 too_large (mirrors
  import); /preview 413 on request body > MAX_BYTES and text > MAX_CHARS (60k) before hash/render. Added a
  real-PDF-with-text extraction test (hand-built minimal PDF w/ correct xref, pypdf extracts it). Python
  1012, frontend 109 + tsc/build; real-HTTP harness: review→token→preview 200 "Hi Dana,", forged→403,
  none→400, changed→403. Note: AS_BUILT + this file carry another agent's uncommitted Ohio-census/reviewer
  entries, so my commit includes only my code/tests + MVP_DELIVERY + the playbook evidence doc; AS_BUILT +
  CONTINUITY are updated in the working tree but left UNCOMMITTED to preserve the other agent's work.

- 2026-10-01T18:53:41Z [TOOL] Independent local recheck of 7f5d99b: 22 focused
  Python and 4 frontend Playbook tests PASS in network-disabled containers.
  [CODE] Preview accepts an arbitrary caller-supplied text/matching-hash pair
  with no server proof of review/selection; upload uses unbounded `read()` before
  its 5 MB check and preview has no text-size bound. The Sheets cell limit is
  a constraint on that storage choice, not proof durable selection is impossible
  with the existing Drive handbook architecture. Evidence:
  docs/testing/playbook-2026-10-01.md. No product code/live service changed.

- 2026-10-01 [BUILD] Playbook PDF/DOCX upload → review → select-by-hash → candidate preview (flag-gated
  enable_playbook, off by default + deploy; local, read-only; no Gmail/send; Drive handbook stays production).
  New outreach/playbook_extract.py (pypdf + python-docx, imported inside fns like importer; rejects
  empty/too_large>5MB/unsupported/malformed/no_text(image-only)/too_long>60k) + outreach/playbook.py
  (review(text) → initial-email + follow-ups (reuse followup.templates) + timing (business-day ints) + offer
  values + missing/ambiguous; content_hash = immutable version id, same normalize as handbook_drive). Console
  under enable_playbook: POST /api/playbook/review (multipart → extract → review) + /preview (text+hash →
  followup.render(1); 409 if content_hash(text)!=selected → changed file must be re-reviewed). Snapshot gains
  playbook_enabled; Layout nav + router "playbook" page + App case gated by it. Frontend Playbook.tsx shows
  extracted text as PLAIN DATA (<pre>, never dangerouslySetInnerHTML, never instructions). requirements.txt
  += pypdf==5.*, python-docx==1.* → HAD TO REBUILD outreach-tests image (docker build -f deploy/test.Dockerfile
  -t outreach-tests .) so the libs are present; regenerated console/src/demo/snapshot.json for the new key
  (test_console_api asserts exact snapshot == fx.snapshot()). Python 1002, frontend 109 + tsc/build. Real API
  (harness, enable_playbook=True): real .docx → review (initial/fu1/fu2, timing [3,7]) → preview "Hi Dana,"
  no problems → changed-file 409; page renders w/ nav link. **DURABLE SELECTION BLOCKER (documented, not
  built):** a Google Sheets cell ≤ 50,000 chars but a playbook may be 60,000 → can't persist the handbook
  text in one cell safely → selection is per-session (client holds text+hash, server re-verifies); don't claim
  durable selection. Not verified: real text-PDF unit extraction (no PDF writer in tests — DOCX covers text,
  PDF covers errors incl. a real blank PDF → no_text); browser-DOM file upload (component + real-API cover it).
  Evidence docs/testing/playbook-2026-10-01.md. Synthetic only; committed, not pushed.

- 2026-10-01T10:33:00-04:00 [TOOL] Independently rechecked af007dc in local
  network-disabled containers: 13 focused frontend tests and typecheck PASS.
  [CODE] App increments generation on every successful snapshot load and passes
  it to LeadPage's candidate key; candidate signature now includes handbook hash
  and evidence. The two previously reported freshness cases are addressed at
  this code/test scope. No browser out-of-band edit or live deployment was
  verified. Evidence: docs/testing/chat-call-review-2026-10-01.md.

- 2026-10-01 [FIX] Recheck of e52c221 found finding 1 still incomplete 2 ways; both closed. (a) read_at is
  minute-precision → same-minute refreshes shared postCallReloadKey → no re-fetch. App now keeps a
  `generation` counter (incremented each successful load), threaded page()→LeadPage→postCallReloadKey(lead,
  data, generation), so the candidate re-fetches on EVERY refresh regardless of the clock. (b)
  PostCallCandidate serverSig now = leadId+subject+body+handbook_hash+JSON(evidence) (was leadId+subject+body),
  so a changed handbook version/evidence with identical text is treated as a changed candidate (edits
  replaced, not preserved under a new basis). Python 980, frontend 105 (LeadPage.test.tsx generation key;
  PostCallCandidate.test.tsx identical-text-changed-hash discards edit) + tsc/build. Test gotcha: a
  mockResolvedValueOnce→mockResolvedValue sequence misaligned across rerenders; use a call-indexed
  vi.fn(()=>...) for deterministic per-call values. Not browser-reproduced (harness can't make a same-minute
  in-place handbook edit). Synthetic only; enable_calls off in deploy; committed, not pushed.

- 2026-10-01T14:03:19Z [TOOL] Independent recheck of e52c221: 55 focused Python
  and 18 focused frontend tests PASS in network-disabled containers. [CODE] The
  candidate refresh remains incomplete: `read_at` has minute precision, so
  same-minute refreshes keep the same key; `serverSig` omits handbook hash and
  cited evidence, so edits can survive a changed source basis with identical
  subject/body. Partial STOP warning and midnight due-date pin are supported by
  code and focused tests. Evidence: docs/testing/chat-call-review-2026-10-01.md.
  No product code or live service changed in this recheck.

- 2026-10-01 [FIX] Chat-call review (docs/testing/chat-call-review-2026-10-01.md) three findings closed;
  interpreter stays read-only, confirm via POST /api/calls/<lead>/outcome. (1) IN-PLACE freshness:
  postCallReloadKey now includes data.read_at → lead page re-fetches the candidate on EVERY snapshot refresh
  (catches a handbook edit at the same URL / offer wording change while approved stays true; the endpoint
  rebuilds from live handbook+settings). PostCallCandidate keeps a serverSig ref (leadId+subject+body of the
  last PRISTINE fetched candidate): same sig on refetch → PRESERVE the founder's edits; different → adopt
  (discard edits); null → withdraw. (2) Chat partial success: CallLogChat.confirm reads the result; on
  suppression_written:false/warning (HTTP 200) shows the warning, KEEPS proposal+submission_id, "Retry the
  suppression write" re-posts the same submission_id (repairs suppression, no 2nd call) — matches CallPanel.
  (3) Preview due == saved due: call_log_chat.interpret returns called_at (interpret clock); CallLogChat.confirm
  posts it; outcome route computes the due from the same call time → no NY-midnight drift (also added called_at
  to recordCallOutcome's TS type). Python 980, frontend 104 + tsc/build (Docker Desktop had to be restarted:
  `& "C:\Program Files\Docker\Docker\Docker Desktop.exe"` then wait ~60s). Browser: regression smoke only (chat
  interpret→confirm→task with matching due; candidate still renders). The 3 fixes NOT browser-reproduced — the
  harness has no controlled clock, no suppression-write-failure injection, no out-of-band handbook/offer change;
  proved by container route/component/pure tests. Synthetic only; enable_calls off in deploy; committed, not pushed.

- 2026-10-01T09:44:48-04:00 [CODE] Local review of ba10c11 found three remaining
  chat/candidate gaps: same-URL handbook or still-approved offer edits leave the
  candidate reload key unchanged; CallLogChat hides a partial STOP suppression
  append and clears the retry identity; no-answer preview/confirm across a New York
  date boundary can change the due date. Evidence:
  docs/testing/chat-call-review-2026-10-01.md. [TOOL] Container checks were
  attempted but Docker Desktop Linux Engine was unavailable; fresh runtime status
  is UNVERIFIED. No product code or live service changed.

- 2026-10-01 [BUILD] Chat-based call logging (flag-gated enable_calls). New PURE outreach/call_log_chat.py
  (deterministic, read-only, no model): detect_outcome (phrase lists, STOP wins), match_leads (company/
  contact tokens; over-match → choose, which is safe), interpret(note, leads, now, rule, chosen_lead_id,
  callback_at) → status unclear_outcome/no_lead/choose_lead/need_time/ready. CALLBACK time NEVER parsed from
  prose — only from an explicit callback_at (UI datetime). New READ-ONLY endpoint POST /api/calls/interpret
  (console.py under enable_calls) returns the proposal; CONFIRM reuses the existing POST
  /api/calls/<lead>/outcome (submission identity, scheduling, STOP/HOLD/sticky DNC). Frontend:
  api.interpretCallNote, types CallProposal/CallProposalLead, CallLogChat.tsx on the Dashboard (SEPARATE from
  the read-only assistant): read→proposal→confirm; choose-lead buttons re-interpret with lead_id; need-time
  datetime input re-interprets with callback_at; ready shows exact lead/note/due/effect + a clear sticky-stop
  warning for DNC; confirm reuses the proposal's submission_id (retry = one event). Python 978 (test_call_log_chat.py
  + endpoint cases in test_console_calls.py), frontend 101 (CallLogChat.test.tsx + LeadPage.test.tsx) + tsc/build.
  Browser (harness, ?r=chat full load): no-answer note → Read it → proposal (exact lead/note/Mon 2026-10-05)
  → Confirm → "Saved" + task in queue (auto-refresh); DNC note → permanent-stop warning. NOT browser-run
  (route/component-tested): choose-lead, need-time, confirm-retry. Matching gotcha: trade words (electric/
  plumbing) cross-match, so unambiguous fixtures need distinct company tokens; over-match → choose is the
  intended safe behavior. Synthetic only; enable_calls off in deploy; committed, not pushed.

- 2026-10-01 [FIX] Post-call candidate freshness: reloadKey only tracked call fields, so an external opt-out
  (or offer-approval/handbook change) with call fields unchanged left a stale candidate after refresh.
  LeadPage now exports postCallReloadKey(lead,data) folding in lead.suppressed + data.approvals.offer +
  data.links.handbook. Regressions: LeadPage.test.tsx (key changes on suppression/offer/handbook, stable
  otherwise) + the component withdraw test. External-opt-out browser repro NOT run (harness has no out-of-band
  suppression write) → proved by unit + route (suppressed→no candidate) + component tests.

- 2026-10-01 [FIX] Post-call candidate: four review gaps (docs/testing/post-call-review-2026-10-01.md).
  (1) EFFECTIVE decision: endpoint computes calls.outreach_effect(events) → refuses call_stop on STOP, and
  post_call.candidate takes effect= and raises on STOP (sticky DNC after a later NO_ANSWER, even with a
  failed suppression write); ordinary suppression.covers kept. (2) offer_approved REQUIRED: post_call.offer_approved
  checks the flag → offer_not_approved; stopped calling wording "handbook-approved" (it's composed in code
  from settings; handbook name/hash only tie it to a version, text not read). (3) No false "today": candidate
  takes now=; "today" only when the saved call's NY date == now's NY date, older call worded with no timing
  claim (all 3 outcomes). (4) Stale candidate withdrawn: PostCallCandidate gains reloadKey prop (LeadPage
  derives it from call_history.length|call_effect|call_task.id) in the useEffect deps → re-fetches on a parent
  refresh after a CallPanel save. Python 958, frontend 92 + tsc/build. Browser (harness, FULL reload via
  ?r=1 — note a hash-only nav does NOT reload the SPA bundle, so after a dist rebuild use a query param or
  base-path nav): NO_ANSWER candidate visible → record DO_NOT_CONTACT via CallPanel → post-call section
  disappears with no manual reload. Gaps 1-3 proved by route/pure tests. Synthetic only; handbook stubbed in
  the harness (offer settings + STUB_HANDBOOK + offer_approved); enable_calls off in deploy; committed, not pushed.

- 2026-10-01 [BUILD] Post-call email candidate (flag-gated enable_calls; candidate-only, no send/Gmail/
  persist). New PURE outreach/post_call.py composes a candidate from latest_call(events) (outcome+note, and
  callback_at only for CALLBACK), the lead's "Offerings evidence" (verbatim company quote), the handbook-
  approved offer (settings signature fields + cta), tied to the handbook content_hash; reuses
  drafting.sign_off (opt-out footer) + verified_first_name. Rules: candidate ONLY for NO_ANSWER/INTERESTED/
  CALLBACK (eligible_outcome); NO_ANSWER never claims a conversation; never invents recipient words; CALLBACK
  uses only the recorded time; no candidate for DNC/NOT_INTERESTED/WRONG_NUMBER/no-email/no-handbook/offer-
  not-configured (raises post_call.NotEligible(reason)). New flag-gated endpoint GET
  /api/calls/<lead>/candidate (console.py, under enable_calls): reads lead+call events+suppression+handbook
  (job_draft._handbook), returns {candidate} or {candidate:null, reason, unavailable?}; reasons no_email /
  outcome_not_eligible (render nothing), suppressed (note), call_log_unreadable / suppression_unreadable /
  handbook_unavailable (unavailable). Frontend: api.loadCallCandidate + types CallCandidate/CallCandidateResult;
  PostCallCandidate.tsx on LeadPage (under CallPanel) fetches on mount, editable subject/body, Discard,
  "what this is based on" (outcome/note/evidence/handbook), disclaimer "not sent, no Gmail draft, a hold still
  pauses the sequence". It authorises nothing + writes nothing (tested: showing it leaves call_events/
  suppression unchanged and call_effect still HOLD). Python 952 (+21: test_post_call.py pure + endpoint cases
  in test_console_calls.py), frontend 91 (+5 PostCallCandidate.test.tsx) + tsc/build. Browser (harness
  EXTENDED with offer SETTINGS + STUB_HANDBOOK via monkeypatching job_draft._handbook + A-0001 Offerings
  evidence — LOCAL ONLY): NO_ANSWER on email lead → candidate card with subject/body/opt-out/evidence/note/
  handbook → reload persists; phone-only A-0002 → no card. Gotcha: a monkeypatch lambda for _handbook must
  not name its 2nd param `handbook` (shadows the captured book → returns None). UNVERIFIED LIVE: real Drive
  handbook, signed-in browser, API latency; handbook stubbed; enable_calls off in deploy. Committed, not pushed.

- 2026-10-01 [FIX] Dashboard call-queue acceptance gaps (review in docs/testing/calls-review-2026-09-30.md).
  (1) The queue now HONOURS SUPPRESSION: console_model.build skips a lead whose view["suppressed"] is truthy
  (opted out) - call_state only knew call-recorded DNC, not the separate Suppression list - and when
  entries is None (suppression unreadable) empties the queue + sets snapshot `suppression_unreadable`; the
  Dashboard passes unreadable = calls_unreadable || suppression_unreadable to CallQueue, which shows the
  unavailable state ("call log or suppression list could not be read", never "no calls due"). The opted-out
  lead keeps its call history on the lead page. (2) Stale-action recovery: QueueItem's refusal keeps the
  server message AND shows a "Reload the queue" button that calls onChanged; after the dashboard re-reads
  and passes the newer task, the next action targets the refreshed task_id (tested STALE→FRESH via rerender).
  (3) Upcoming items now include contact + note (were company/phone/due/reason only). Python 933 (+2 route
  tests: opt-out excluded while a non-suppressed stays; unreadable suppression → flag+empty), frontend 86
  (+3: Cancel/Snooze bound to id, stale→Reload→refreshed id, upcoming contact+note) + tsc/build; regenerated
  demo snapshot.json (new key suppression_unreadable - the equality test needs the --write regen, RW mount).
  Browser (harness, fixed real clock): overdue past-callback → Snooze to 2026-12-01 via the UI (form_input
  on the datetime-local by ref; clicks need a retry when the pane is hidden) → moved out of overdue → reload
  shows "1 upcoming" (persisted). Browser evidence vs controlled-clock route tests kept distinct. Synthetic
  only; enable_calls off in deploy; committed locally, not pushed.

- 2026-09-30 [BUILD] Dashboard call queue (flag-gated enable_calls). console_model.build gives each open
  task a `when` bucket (OVERDUE/TODAY/UPCOMING, from the NY date, same clock as overdue), carries the task
  `id`, and the snapshot adds `calls_due_today` + `calls_unreadable`. New CallQueue component
  (console/src/pages/CallQueue.tsx) on the Dashboard: overdue first, then due today, upcoming in a separate
  <details>; each item = company (link to lead), contact, phone, due date/time, reason/note; reuses
  actOnCallTask (task_id required) for Complete/Snooze/Cancel; a stale 409 shows the server message +
  refreshes; unreadable Call log → an UNAVAILABLE state, never "no calls due". App passes onChanged=refresh
  to Dashboard. Phone-only + email+phone both appear; complete/cancel remove, snooze moves, survive reload.
  Containers: Python 931 (+3 route tests: buckets on a controlled clock, upcoming separate, unreadable →
  calls_unreadable+empty), frontend 83 (+5 CallQueue.test.tsx) + tsc/build; regenerated demo snapshot.json
  (console_fixture.py --write in a RW-mounted container — the equality test test_the_react_apps_demo_data_is_this_fixture
  would otherwise fail on the new keys). Browser (harness, fixed real clock): no-answer + past-callback → 1
  overdue + 1 upcoming with phone/reason → Complete removes it + auto-refresh → reload confirms gone. Clock-
  advance overdue transition is covered by controlled-clock route tests (harness can't advance its clock).
  Synthetic only; enable_calls off in deploy; committed locally, not pushed.

- 2026-09-30 [FIX] Call-history contract aligned: job_draft._call_effect now matches sheet.Store.call_events
  for all three cases — absent tab = no calls (CONTINUE); valid header + no events = no calls; present tab
  WITHOUT the required header (incl. an empty headerless tab) = unreadable → block (fail closed). Removed
  _call_effect's `if not values: return CONTINUE` early return so the header check governs. Regressions:
  test_sheet_append.py::test_call_events_contract_absent_valid_header_and_missing_header (Store, 3 cases) +
  test_draft_pipeline.py (valid-header-no-events still CREATED; present headerless tab → DraftBlocked, no
  Gmail create). Python 928. NEXT MILESTONE NOT STARTED (usage limit): dashboard call queue — overdue-first/
  due-today/upcoming buckets, reuse task identity + Complete/Snooze/Cancel, unavailable state when call
  history unreadable. build already emits call_tasks (overdue-first) + calls_overdue; needs a `when` bucket
  per task, a `calls_unreadable` flag from the snapshot, a dashboard component, and a browser journey.

- 2026-09-30 [FIX] Call-task recheck (docs/testing/calls-review-2026-09-30.md "Independent recheck" of
  829c309): three enforcement-boundary gaps closed, earlier fixes preserved. (1) STOP/HOLD now enforced at
  job_draft.create (the REAL initial Gmail-draft boundary the worker create route calls; drafts.plan is only
  candidate selection, so a candidate approved BEFORE a call decision bypassed it). New job_draft._call_effect(api,
  lead_id) re-reads the Call log at the boundary with the SAME header contract as sheet.Store.call_events (titles →
  missing tab = CONTINUE so calls-less companies still draft; present+bad-header or read error = DraftBlocked, fail
  closed); create refuses STOP/HOLD/unreadable before any reservation or Gmail write; signing + all gates unchanged.
  (2) task action requires a nonempty task_id — removed the `client_task_id or task["id"]` fallback; route 400 on
  missing/blank, 409 on stale; typed actOnCallTask makes task_id required; CallPanel doAction guards `!task`. (3)
  CallPanel now READS the outcome result: on suppression_written===false (or warning) it shows what saved + what
  remains, KEEPS the submission id + form, and offers "Retry the rest" (re-sends the same submission id → no 2nd
  call). Containers no-net: Python 925 (+5: create blocked by DNC-no-suppression / CALLBACK-HOLD / unreadable, each
  asserting no Gmail create; eligible no-call-history still CREATED; task action missing/blank/stale refused, newer
  task untouched), frontend 78 (+2: partial-warning renders + Retry reuses id; real recordCallOutcome parser
  round-trips the partial shape) + tsc/build. Browser (real API): task action no/blank task_id → 400, task stays
  scheduled, correct id completes. Gap-1 has no UI (Gmail drafting off) and gap-3's warning needs a suppression
  failure the harness store can't inject → covered by component-render + parser + server-route tests, not a browser
  run. Test wiring: ready fixture (test_draft_pipeline) now patches job_draft._call_effect→CONTINUE by default (else
  api=object() crashes); gap-1 tests restore _REAL_CALL_EFFECT (captured before ready patches) + a
  test_sheet_append.FakeSheets seeded with a Call log tab (header row 1, no title row). Synthetic only; live NOT done;
  enable_calls off in deploy; committed locally, not pushed.

- 2026-09-30 [FIX] Call-task correctness, the four findings in docs/testing/calls-review-2026-09-30.md
  (against 52bebbd), all fixed + regressed through the REAL routes and the pure state machine (not mocks
  alone). (1) STOP/HOLD now enforced in eligibility: `calls.outreach_effect`/`blocks_outreach` (no clock);
  `drafts.first_draft_blockers` + `followup.due_now` take call events and skip STOP/HOLD leads (offline HOLD
  enforcement now exists); unreadable call log fails closed in drafts.plan / followup.pending_reviews+run /
  console_model.snapshot+build; the outcome route reports `suppression_written:false` + `warning` and the
  STOP is still enforced via the recorded call event. (2) do-not-contact is STICKY (call_state
  `do_not_contact` flag): a later no-answer never reopens a task or lifts STOP; history still logged;
  not-interested stays distinct. (3) task action bound to the exact task: new "Task ID" column
  (sheet.CALLS_HEADER, calls.action_event) persists the target, call_state applies an action only to the
  named task (stale/interleaved can't close a newer one); call_task_view exposes `id`; CallPanel sends
  task_id; route 409 on mismatch without touching the newer task. (4) retry-stable UI submission: CallPanel
  keeps one submission_id across retries (cleared on success/edit), calls.outcome_event uses it as the Event
  ID (UI omits called_at), so a retry after a lost response makes no duplicate; a fixed-called_at
  programmatic caller keeps content-hash idempotency. Containers: Python 920 (+14), frontend 76 (+2),
  tsc+build clean. Browser (tools/local_import_console.py:8139, real built pages): phone-only DNC then
  no-answer stays "No call scheduled" + STOP + first-draft blocker; stale task_id -> 409, newer task stays
  scheduled; two UI-shaped submits 1s apart -> one history row. Synthetic only; live NOT done; enable_calls
  off in deploy. Gotcha: local host python lacks googleapiclient/flask -> run pytest AND the harness inside
  the outreach-tests image (repo mounted ro); build console/dist via outreach-console-tests with src mounted
  ro + dist mounted rw; the harness needs a network for -p (never --network none), it never calls Google.

- 2026-09-30 [BUILD] First call-task workflow (local, flag-gated `enable_calls`, off by default+deploy).
  `outreach/calls.py` (pure): outcomes (no answer/interested/not interested/callback/wrong number/do not
  contact) + actions (complete/snooze/cancel) as an append-only event log; `call_state` replays to the
  current task + history + email effect. No-answer schedules by `call_no_answer_business_days` (default 3,
  NY dates); callback uses the explicit time; a note is never parsed. Event ID => repeated submission is a
  no-op. `sheet.py` Call log tab (`call_events`/`append_call_events`, idempotent); do-not-contact/not-
  interested also write Suppression (STOP the offline scheduler honours). `console.py` POST
  /api/calls/<lead>/outcome and /task; `console_model` adds per-lead call_task/history/effect + top-level
  call_tasks/calls_overdue. Frontend CallPanel on the lead page (log a call; due/overdue + complete/snooze/
  cancel; effect note; history); api recordCallOutcome/actOnCallTask; datetime-local sent as real instants.
  Containers: Python 906, frontend 74, tsc+build. Browser: log No answer -> task due Mon 2026-10-05 ->
  survives reload -> Complete clears it. Email effect: STOP via suppression (enforced), HOLD persisted+shown
  (offline enforcement a next step). REMAINING in call milestone: post-call email candidate, chat logging,
  offline HOLD enforcement, dashboard overdue list. Live verification separate + NOT done (enable_calls off).
  Ordering gotcha fixed: call_state stable-sorts by Recorded-at only (append order), so an action never
  sorts before its outcome. Regenerate demo snapshot.json + rebuild the test image before the demo test.

- 2026-09-30 [FIX] Import overlapping original-vs-resume duplicate (the review below). Removed
  write-taking Resume: `commit` now sets `writable = won`, so ONLY the request holding the earliest
  ledger claim ever writes a lead; a resume/any other request does read-only reconciliation and reports
  `mine_prior` as `pending`, never writing it. Ownership guarantee: append-only ledger + read-after-own-
  append => exactly one `won` per lead => two requests can never both append it (no pause/overlap breaks
  it). Repro-then-fixed: `test_overlapping_original_and_resume_write_the_lead_once` (pause original's lead
  append after its recheck via a one-shot FakeSheets pause outside the lock; run a same-op resume through
  a second app; release; ONE row). Plus `test_simultaneous_resumes_of_an_abandoned_claim_write_nothing`.
  Frontend shows done/pending("cannot be completed automatically yet" + read-only Check again)/blocked/
  uncertain. Containers: Python 883, frontend 70, tsc+build. REMAINING (documented, unmet): automatic
  recovery of a lead whose owner failed BEFORE writing is not available (resume => pending; different key
  => blocked); safe takeover needs a fenced lease/CAS (separate architecture decision, not made). Milestone
  record corrected: concurrency/dup-prevention PASSES locally; abandoned-pre-write-claim recovery INCOMPLETE
  by design; deploy-off != concurrency-safe; live verification a separate milestone (enable_import off).

- 2026-09-30T22:05Z [TOOL] ce9cc4b targeted importer/routes/adapter tests: 42 passed.
  Deterministic two-app probe pauses original append after its fresh read, starts same-op
  resume, then releases both: both done/written=1, two physical copies of one ID.
  Resume makes mine_prior writable without stopping the old attempt; sequential late
  completion test misses overlap. Supersedes local acceptance/unreachable-race claims
  below. Evidence appended to docs/testing/import-review-2026-09-30.md. No product edits/live writes.

- 2026-09-30 [FIX] Import coordination/recovery (the review below). Claims ledger now carries
  Op key + Attempt; `claim_leads` classifies won/mine_prior/other and a request writes only "won",
  so two attempts sharing an idempotency key resolve to ONE writer (fix 1). An append exception whose
  reconciliation READ also fails is an explicit `outcome:"uncertain"` (never "nothing written"; only a
  successful read showing absence is nothing-written) (fix 2). Commit returns done/pending/blocked/
  uncertain; the client keeps the op key per preview fingerprint in localStorage so a reload resumes the
  SAME operation; `resume` takes over its own op's mine_prior leads; `append_leads` rechecks presence
  before writing so a late straggler adds no dup; the Import page shows pending/blocked/uncertain +
  Resume/Check (fix 3). Constraint documented: no atomic CAS on Sheets => exactly-once NOT claimed;
  single writer per concurrent round + bounded late completion; abandoned claim recovered by same-op
  resume (no TTL takeover). Containers: Python 882, frontend 70, tsc+build; browser happy-path sanity.
  LOCAL import acceptance criteria pass; live verification separate + NOT done; enable_import off in deploy.

- 2026-09-30T21:35Z [TOOL] Reviewed b49226c: 37 targeted container tests pass;
  old two-write allocator removed. Real-route/adapter probes still reproduce same-key
  concurrent duplicate rows, false Nothing was written after a landed append plus
  failed reconciliation read, and abandoned claim blocking a fresh-key re-import.
  Supersedes duplicate-prevention/re-import recovery claims below. Evidence appended
  to docs/testing/import-review-2026-09-30.md. No product edits or live writes.

- 2026-09-30 [FIX] Replaced the import Lead ID allocation + retry mechanism (the follow-up
  below). IDs are now a stable, immutable content hash (`importer.stable_lead_id`, `{prefix}-{12hex}`,
  disjoint from legacy `{prefix}-NNNN`) assigned before the write and written in ONE append, so
  (1) no collision with an existing numeric id and (3) no second position-based write for a sort to
  corrupt. (2) Retries reconcile by id (an uncertain append is re-read, not assumed failed) and
  `prepare_commit` skips ids/content already present. Cross-instance duplicates are prevented by a
  claim ledger (`Store.claim_leads`, append-only `Import claims` tab, earliest claim wins, gated by a
  required client idempotency key): two independent apps importing the same list write each lead once.
  Consumer survey done before choosing the format (tier_of/fresh_lead/_lead_order/job_check all OK).
  Containers: Python 877, frontend 68, tsc+build; browser sanity check via the real local API.
  Bounded limit: a claim winner that fails and never retries needs a re-import (TTL+sweep proposed,
  not built); no live Sheet write; enable_import off in deploy. Evidence: the Remediation-of-the-
  allocator-follow-up section in docs/testing/import-review-2026-09-30.md.

- 2026-09-30T21:07Z [TOOL] Independent follow-up of `e1f8eb2`: 35 targeted import
  tests pass in a network-disabled container. New allocator probes reproduce an
  existing A-0002 collision, invisible ID-less row after the second write fails plus
  duplicate on retry, and overwrite of an existing ID when rows sort between append
  and ID write. Supersedes the collision-free claim below; import remains incomplete.
  Evidence appended to docs/testing/import-review-2026-09-30.md. No product edits/live writes.

- 2026-09-30 [FIX] Remediated the three import acceptance failures from the review
  below. (1) `importer.fingerprint` now covers the destination columns and the commit
  route revalidates them → a changed destination is refused (409); `Store.append_leads`
  refuses field loss (`DestinationMismatch`) instead of dropping. (2) Lead IDs come from
  the atomic append's row (`updatedRange`), not `max+1`, so concurrent instances get
  distinct IDs (regression via two Flask apps on one simulated Sheet + a barrier).
  (3) Invalid contact values are preserved as validation feedback on accepted/skipped
  rows and shown on the Import page. Containers: Python 875, frontend 68, tsc+build.
  Browser-verified through the real local API (validation + stale-destination 409).
  Limits: cross-instance dedupe is best-effort (may create two rows, distinct IDs); a
  row id could clash with a sparse legacy id; no live Sheet write; `enable_import` off in
  deploy. Evidence: docs/testing/import-review-2026-09-30.md (Remediation section).

- 2026-09-30T17:26Z [TOOL] Reviewed import milestone `03a29c7`; three synthetic
  container probes reproduced: removing Phone after preview returns success but loses
  the number; two app instances append the same A-0002 ID; invalid email/phone values
  disappear without validation feedback. Evidence: docs/testing/import-review-2026-09-30.md.
  M2 is incomplete on these acceptance criteria. No product-code edits, live writes,
  deployment or full-suite rerun during this review.

- 2026-09-23T03:39Z [TOOL] Before the fix, an old-template hash could reach the Gmail
  draft path without a Drive handbook. Word overlap also accepted a negated quote as a
  positive company claim and "MVP is finished" from a "still being finished" handbook.
  After the fix, 255 tests pass offline in a network-disabled container. Lexical screening
  remains insufficient to prove semantic support; exact source review is required.

- 2026-09-23T03:00Z [TOOL] Read-only status check: 492 leads have email-check
  outcomes; 69 have fit verdicts, 5 company profiles are READY, 26 are
  OK/QUALIFIED, and no Sheet row has a draft action. Suppression exists with
  only its header. Cloud Run still routes 100% to worker revision 00013 and
  the check schedule is PAUSED. `docs/AS_BUILT.md` summary corrected; the
  planned Drive/Gemini writer remains unbuilt.

- 2026-09-22T20:48:00-04:00 [TOOL] Read-only previews of four READY leads after
  the selection fix choose commercial gas-line work for Monroe, a project
  portfolio for Conti, and the prior Harrington sentence. Cincinnati Air has
  no clean complete-sentence default among its four stored quotes; it remains
  held for an explicit reviewed choice or better source evidence.

- 2026-09-22T20:24:00-04:00 [CODE] The Cloud Run source ignores `docs/`, so the
  runtime initial-email template lives under `outreach/handbook/` while the
  review handbook stays in `docs/`.

## [OUTCOMES]

- 2026-10-01T03:23:26Z [TOOL] Independent recheck of post-call fix 428b56a:
  47 Python and 6 component tests pass offline. Effective STOP, offer approval,
  date-aware copy and reload on call change inspected. One residual UI freshness
  gap: same-lead snapshot refresh after external suppression (or offer/handbook
  change) leaves candidate visible because reloadKey tracks only call fields.
  Evidence: docs/testing/post-call-review-2026-10-01.md. No product/live edits.

- 2026-10-01T03:06:55Z [TOOL] Reviewed post-call candidate d107e01: 41 Python
  and 5 component tests pass offline, but a real-route synthetic DNC plus failed
  redundant suppression write then NO_ANSWER still offers a candidate while
  effective call decision is STOP. Unapproved offer also produces a candidate;
  historical calls are phrased as happening today. Inspection: candidate UI
  does not reload on same-lead snapshot refresh. Evidence:
  docs/testing/post-call-review-2026-10-01.md. No product/live edits.

- 2026-10-01T02:47:29Z [TOOL] Independent scoped check of dashboard queue fix
  8d8d278: 50 Python and 8 CallQueue UI tests pass offline; inspected suppression
  exclusion/unavailable state, stale Reload, and upcoming contact/note. Accept the
  local queue milestone. Claude reports browser Snooze/reload; not independently
  rerun. Evidence: docs/testing/calls-review-2026-09-30.md. No product/live edits.

- 2026-10-01T02:31:57Z [TOOL] Reviewed dashboard queue f509dbb: 64 targeted Python
  and 13 queue/panel UI tests pass offline. Real snapshot probe still queues an
  opted-out/suppressed lead; unknown suppression also leaves queue actionable.
  Inspection: stale error does not refresh; upcoming items omit contact/note.
  Dashboard snooze/cancel verification not established by reported browser trace.
  Evidence: docs/testing/calls-review-2026-09-30.md. No product/live changes.

- 2026-10-01T02:18:28Z [TOOL] Independently verified 7053b63 with 95 targeted
  draft-pipeline/Sheet-adapter tests passing offline. Scoped call-history header
  contract fix accepted. Dashboard queue still not implemented; next milestone
  unchanged. Evidence appended to docs/testing/calls-review-2026-09-30.md.
  No product/live changes, no broader test or browser rerun.

- 2026-10-01T00:05:25Z [TOOL] Rechecked 0a85b45: 196 targeted Python and 8
  CallPanel tests pass offline. Three prior reproduced gaps addressed locally;
  real-route partial-suppression retry leaves one call and one suppression row.
  One narrow discrepancy: existing blank Call log is refused by Store but treated
  CONTINUE by job_draft._call_effect. Align header contract, then advance dashboard
  due/overdue call queue. Evidence: docs/testing/calls-review-2026-09-30.md.
  No product/live changes; build/browser/full-suite not rerun by this reviewer.

- 2026-09-30T23:42:59Z [TOOL] Rechecked 829c309: 115 targeted Python and 6 CallPanel
  tests pass offline. Original retry/sticky-DNC fixes improved, but synthetic
  job_draft.create still calls fake Gmail despite stored STOP/HOLD plus valid prior
  approval; missing task_id still closes the newer task. CallPanel ignores the new
  partial-success warning (inspection). Evidence appended to
  docs/testing/calls-review-2026-09-30.md. All-four-fixed claim not yet supported;
  no product code/live operations changed in this review.

- 2026-09-30T22:45:34Z [TOOL] Independent local review of call milestone 52bebbd:
  23 targeted tests pass in a network-disabled container. Additional real-route
  synthetic probes show STOP reported despite failed suppression write, phone-only
  DNC replaced by NO_ANSWER, stale Complete closing a newer callback, and actual UI
  retry payload recording two call events. Worker HOLD enforcement is still absent.
  Evidence: docs/testing/calls-review-2026-09-30.md. No product-code/live changes;
  finish these call behaviors before expanding the milestone.

- 2026-09-30T22:18Z [TOOL] Independently verified 0b6ed5c with 43 targeted import
  tests in a network-disabled container. Specific original-write/resume overlap now
  writes one row; simultaneous checks of abandoned claims write none. Scoped race fix
  accepted; automatic abandoned-import recovery and live verification remain open.
  Evidence: docs/testing/import-review-2026-09-30.md. No product-code or live changes.

- 2026-09-30T16:24Z [CODE] Continued the narrow review-status task from existing local
  `4c8f896` (descends from requested `f939d4a`). Removed the missing-state permission
  exception; API type, demo and fixtures require explicit state. [TOOL] 63 frontend
  tests, typecheck, production/demo builds and unchanged backend's 832 tests passed
  in network-disabled containers. Original component and missing-state exception each
  failed the relevant regression. Evidence: docs/testing/review-status-2026-09-30.md.
  Signing/gate unchanged; no deployment, activation, permission change or Google writes.

- 2026-09-22T20:24:00-04:00 [ASSUMPTION] Real pilot remains UNVERIFIED until the
  founder supplies the offer, sender details, and postal address and approves
  actual preview hashes. See `docs/AS_BUILT.md` for current verification.
