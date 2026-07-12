# Security Policy

## Reporting a Vulnerability

Use GitHub private vulnerability reporting when it is available for this repository. Do not open a
public issue containing credentials, cookies, storage-state data, request headers, private media
URLs, or other sensitive artifacts.

If a public issue is necessary, provide only a sanitized reproduction and remove all account and
session data first.

## Sensitive Local Data

The following paths are intentionally ignored and must remain private:

- `storage/storage_state.json`
- `output/debug/`
- `logs/`
- `models/`

Rotate or revoke any credential that is accidentally disclosed before cleaning repository history.
