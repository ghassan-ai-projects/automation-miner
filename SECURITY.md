# Security Policy

## Supported versions

Security fixes target the latest release line.

| Version | Supported |
| --- | --- |
| 0.1.x | Yes |
| Earlier | No |

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability.

Use GitHub private vulnerability reporting from the repository's **Security** tab. If
that option is unavailable, contact the maintainer through
[ghassan-alhamoud.com](https://ghassan-alhamoud.com) without including sensitive
details in a public message.

Include the affected version or commit, reproduction steps, impact, and any proposed
mitigation. You should receive an acknowledgement within seven days.

## Sensitive inputs

Automation Miner processes documents that may contain confidential information. Keep
knowledge bases, generated mining workspaces, local configuration, and provider keys
out of Git. Review provider data-handling terms before sending sensitive inputs to a
hosted model.

## Untrusted document content

Documents are model input, not model instructions. A source file can contain
instruction-like text intended to influence the critic, scorer, or another role.
The pipeline marks evidence blocks as untrusted data and tells roles to ignore
commands embedded in them. This is a mitigation against accidental instruction
following, not a complete security boundary: a model may still make a bad
judgement. Deterministic checks independently validate structured output and
ensure cited evidence IDs resolve to the run's evidence index; ID resolution does
not prove that the cited text semantically supports every claim.

Do not use a hosted provider with sensitive or production documents unless the
provider's retention, region, training, and contractual controls have been
reviewed and approved. For evaluations, use redacted, non-production material.
