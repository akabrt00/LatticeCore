# Security audit report

Date: 2026-07-30

Follow-up: 2026-08-28

## Environment

- Node.js 24.15.0, npm 11.12.1.
- Python 3.13.0.
- The application and worker bind to `127.0.0.1`.
- The audit covered the current uncommitted worktree and a physical clean-room copy.

## npm finding before remediation

`npm audit --json` reported one high-severity transitive development dependency:

- Package: `postcss` 8.5.16.
- Advisory: `GHSA-r28c-9q8g-f849`.
- Title: PostCSS path traversal in previous source-map auto-loading.
- CWE: CWE-22.
- CVSS: 7.5 (`CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:N/A:N`).
- Affected: `<=8.5.17`.
- Patched: `8.5.18` and newer.
- Dependency path: `latticecore -> vite@8.1.3 -> postcss@8.5.16`.
- Relationship: indirect/transitive, development only.

The machine-readable npm result was captured in both the original tree and the clean-room
environment. npm briefly returned an inconsistent zero-vulnerability response for the same
8.5.16 lockfile; the installed version and the GitHub advisory were therefore also checked
directly instead of treating the short audit result as authoritative.

## Reachability

The vulnerable code is PostCSS previous source-map auto-loading. It becomes relevant when
attacker-controlled CSS containing a `sourceMappingURL` comment is parsed without `map: false`.

LatticeCore accepts STL and OBJ uploads only. Uploaded geometry is passed to the Python geometry
worker and never to PostCSS. CSV, JSON, ZIP, SSE and job metadata are also not parsed as CSS.
PostCSS is present under the Vite development/build toolchain and is not included as executable
code in the browser production bundle.

Classification: **development-only and not reachable in the current upload architecture**.
This is a code-path conclusion, not a claim that vulnerable PostCSS is safe in every use. It
would become potentially reachable if LatticeCore later accepted untrusted CSS or exposed a
CSS transformation endpoint.

## Remediation

The Vite 8.1.3 dependency range allows `postcss ^8.5.16`. A scoped patch update changed:

- `postcss` 8.5.16 to 8.5.25;
- `nanoid` 3.3.15 to 3.3.16 as PostCSS's compatible patch dependency.

No direct PostCSS dependency, override, major upgrade, broad dependency upgrade, or
`npm audit fix --force` was used. `package.json` application dependencies did not change.

After remediation:

- `npm audit --json`: 0 vulnerabilities.
- Clean `npm ci`: passed.
- Server and Python tests: passed.
- Production build and clean-room worker startup: passed.
- HTTP geometry and export smoke tests: passed.

## 2026-08-28 follow-up

A later registry audit introduced `GHSA-2v37-7h3g-55p8` for Nano ID versions below
3.3.18. The installed transitive version was therefore updated from 3.3.16 to 3.3.18
within the existing compatible range. No direct dependency, major version or forced audit
fix was added.

Follow-up verification:

- `npm ls postcss nanoid`: PostCSS 8.5.25 and Nano ID 3.3.18.
- `npm audit --json`: 0 vulnerabilities.
- Full server, Python and production-build checks: passed.

## Remaining risk and distribution guidance

- The regular local runtime currently uses the Vite development server. It remains localhost-only
  and the affected package is patched, but a future packaged release should serve `dist` plus the
  worker API without HMR.
- Keep the STL/OBJ allowlist and 100 MiB upload limit.
- Re-run the audit when Vite or PostCSS changes.
- The production JavaScript chunk warning is a performance concern, not this advisory.

Primary advisory:
<https://github.com/advisories/GHSA-r28c-9q8g-f849>
