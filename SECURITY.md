# Security Policy

## Reporting a vulnerability
Send a private report to the repository owner before public disclosure.
Include:
- affected component and version,
- reproduction steps,
- potential impact.

## Secret handling
- `.env` must stay untracked.
- Rotate any token immediately if exposed.
- If a secret is committed, remove it and consider history rewrite.
