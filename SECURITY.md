# Security Policy

Please **do not open a public issue** for a vulnerability. Use GitHub's
[private vulnerability reporting](../../security/advisories/new) for this repository, with steps to reproduce.
We aim to acknowledge reports within a few days.

In scope: the backend API, API-key storage (`backend/app/vault.py`), access control (`backend/app/access.py`),
the code-check sandbox and exported repos. RAGLabs is designed to run locally; if you expose it on a network,
set `ALLOWED_HOSTS`, keep `TRUST_LOOPBACK` appropriate for your proxy and use project API keys (see `.env.example`).
