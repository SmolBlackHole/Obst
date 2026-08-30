# Security policy

OBST is experimental. Security fixes target the current `main` branch. Old
commits, pre-freeze wire drafts and private prototypes are not supported
releases.

## Report a vulnerability

Do not publish exploit details, malicious containers or an undisclosed
vulnerability in a public issue or pull request.

Use GitHub private vulnerability reporting when the repository offers it. If
no private channel is available, open a public issue containing only a request
for private contact. Do not include logs, secrets, proof-of-concept data or
technical details there.

Once a private channel exists, include the affected commit or version, Python
and operating-system versions, expected impact, and the smallest safe
reproduction you can provide.

Useful reports include:

- malformed container bytes escaping validation or configured resource limits;
- container bytes causing plugin discovery, activation or code execution;
- disabled or unselected plugins being loaded;
- portable-file extraction escaping its destination or bypassing publication
  guarantees; and
- untrusted metadata reaching an unsafe terminal or structured-output sink.

## Plugin trust boundary

Installed third-party plugins are trusted Python code, not sandboxed data.
Plugin discovery and persistent enablement inspect package metadata and local
state without importing plugin modules. Building a runtime, invoking a
plugin-contributed command, or running `obst plugins test` executes selected
plugin code with the current process privileges.

OBST deliberately does not provide a plugin sandbox, permissions model or
privilege boundary. Only activate plugins you trust. Run uncertain plugins in
an operating-system process, container or virtual machine whose permissions
match the risk.

A malicious plugin that the host explicitly trusted is normally a problem in
that plugin. It becomes an OBST toolchain issue when the trust boundary itself
fails, for example when a disabled plugin loads or container bytes expand the
active trust set. The full model is documented under
[Plugin trust boundary](docs/toolchain/plugins.md#trust-boundary).

## Repository defenses

Repository maintainers should keep GitHub secret scanning and push protection
enabled. CI also scans repository changes, installed Python dependencies and
the Python codebase. These checks reduce risk; they do not make selected plugin
code safe to execute.

## Integrity is not authenticity

Container CRCs, hashes and the terminal commit detect corruption and bind the
stored representation. They do not authenticate a producer. An attacker who
can replace the complete container can also recompute its integrity data. Use
an authenticated outer channel or a separate signature contract when producer
identity matters.
