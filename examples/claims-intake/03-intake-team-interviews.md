# Intake team interview notes — May 2026

> **Synthetic example** for automation-miner evaluation. Fictional organization and people.

Interviews run by the Operations Excellence team with 5 intake staff and 2 downstream
handlers. Quotes are paraphrased.

## Email/paper intake clerks (3 interviewed)

- "Half my morning is reading emails that are not new claims at all — 'where is my
  repair money', 'here is the missing police report for claim 4711'. They land in the
  same schaden@ mailbox and I have to find the existing claim and forward or attach."
  Team lead estimate: **38% of schaden@ emails are follow-ups to existing claims**, not FNOLs.
- Photos arrive as 10–20 phone pictures per email, often 30+ MB. Clerks drag each into
  ClaimsDesk because the bulk upload "breaks on big files".
- The paper Schadenanzeige forms from the mailroom are often hand-written; clerks re-type
  them from the TIFF in DocuWare in a second window.
- Policy lookup without a number: "I try plate, then name, then I call the customer.
  Sometimes the plate is in the photo of the damage so I zoom in."
- After the February hail storm the team worked Saturdays for three weeks; two temps were
  hired but needed ~2 weeks of training before they could classify complexity reliably.

## Hotline agents (2 interviewed)

- Agents fill a ClaimsDesk free-text note while talking, then the next morning a clerk
  turns the note into structured fields. "We basically type everything twice."
- Callers often do not know whether they have Teilkasko or Vollkasko; agents check
  PolisPro in a second screen while on the call. Average call: 11 minutes.
- No script for injury claims; experienced agents know to ask about hospital visits,
  newer agents forget and Senior Handling has to call back.

## Downstream handlers (2 interviewed)

- Regional handler: "Every Monday I send 10–15 claims back to intake or to another region
  because the postcode belongs to another region or it was clearly complex."
- Senior Handling: injury claims often arrive classified as `standard` because the injury
  is mentioned only in an attached police report, not in the email body.
- Both handlers rely on the acknowledgement letter being sent; when it is late, customers
  call them directly, "which costs me an hour a day after storms".

## Systems landscape (confirmed by IT, May 2026)

- PolisPro (policy admin): AS/400, read-only SQL replica available nightly; no real-time API.
- ClaimsDesk: REST API for claim creation, document upload (max 25 MB per file), and status.
- DocuWare: scanned mail, API available, used today only by the mailroom.
- Outlook / Exchange Online shared mailbox `schaden@`, Microsoft 365 E3 tenant (EU region).
- The company already licenses Azure OpenAI (EU data zone) for an internal policy-wording
  chatbot pilot; IT security approved it for personal data with a DPIA in 2025.
