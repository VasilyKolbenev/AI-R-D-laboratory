# Security · local Windows alpha

## Supported boundary

v0.20.0-alpha.1 is a single-owner application bound to `127.0.0.1`.
Host/Origin checks and a local CSRF token protect browser mutations. They are
not user accounts or tenant isolation. Do not expose the port through a proxy,
tunnel, port forwarding or a public network interface.

The selected installed CLI runs under the current Windows user. Tool restrictions
reduce scope but are not an OS sandbox. Use a trusted profile; do not give the
application administrator privileges.

Selected source text, memory and instructions are sent to the chosen provider
after approval. Web retrieval and Telegram contact external services. Provider
terms, retention and account limits apply independently.

## Data and credentials

- `.lab-data` contains sources, memory, exact prompts, results and receipts.
  These may be sensitive even without an API key.
- Supported local secrets use Windows DPAPI. This protects stored credentials
  in the profile, not against malicious software running as that user.
- Full backups contain sensitive data and encrypted credentials. They remain
  local by default and may require the same profile to decrypt.
- `.gitignore` excludes runtime data and tools; it cannot remove a secret
  already committed to Git. Review files before publishing.
- A timeout may leave an external outcome unknown. Do not assume it was free
  or retry a publication before checking its destination.

No vulnerability-free, always-on or production SaaS claim is made. Only the
local Windows deployment path is supported in this release.

## Report a vulnerability

Use **Security → Report a vulnerability** privately if available:
https://github.com/VasilyKolbenev/AI-R-D-laboratory/security/advisories/new

If unavailable, open an issue asking for a private contact without posting
exploit details, credentials or personal data. Do not attach the working database,
backups, raw prompts or pairing codes.

Include the affected release, Windows/Python versions, synthetic reproduction,
expected boundary and impact. Confirmed fixes identify affected versions in
release notes. No response SLA or external security audit is promised.
