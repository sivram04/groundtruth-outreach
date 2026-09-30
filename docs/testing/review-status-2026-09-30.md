# Review-status API/UI verification

Recorded by Codex, 2026-09-30T16:24Z. Scope: local review-status contract only.
Starting checkout: `4c8f8966837c0fc07d98a21412962112ff42f381`, already containing
the requested fix on top of `f939d4a`. This follow-up requires an explicit state;
it removes the missing-state exception and updates demo/test responses.

## Acceptance criteria

- The real `loadReview` / `recordReview` response parser and React component handle
  confirmed -> rejection recorded/status unavailable -> HTTP 200/unreadable reload
  without enabling Confirm/Reject or showing the old confirmation. A subsequent
  resolved rejection restores the correct status and actions.
- Initial unverifiable (missing verification configuration), conflicting, tampered,
  unreadable, absent, null and unknown states block actions, preserving candidate
  and evidence. Blocked states offer Reload. Genuine `REVIEW_MISSING` permits review.
- Signing, chain resolution and the worker gate remain intact. All checks are local
  containers with networking disabled at run time; no live service is exercised.

## Recorded attempts

| Attempt | Result | Evidence |
| --- | --- | --- |
| New absent/null/unknown/unreadable cases against `4c8f896` implementation | Expected regression failure, exit 1 | `Review.test.tsx`: 1 failed (undefined state), 3 passed, 13 skipped. Missing state incorrectly rendered Awaiting your review. |
| Current frontend, with explicit-state fix | PASS, exit 0 | 63 tests passed across 4 files, including all 17 review tests; `tsc --noEmit` and production Vite build succeeded. |
| Current regression with only `Review.tsx` replaced by its `f939d4a` contents inside a disposable container | Expected regression failure, exit 1 | The requested saved-rejection/reload test failed at the unreadable reload; rendered DOM said Awaiting your review. 1 failed, 16 skipped. Working tree was not changed. |
| Demo build with explicit review states | PASS, exit 0 | Vite demo build succeeded, 1904 modules transformed. |
| Python/backend at `4c8f896` (unchanged by this follow-up) | PASS, exit 0 | `python -m pytest -q tests`: 832 passed in 4.25s, including signing/gate and console response tests. |
| Whitespace check | PASS, exit 0 | `git diff --check`; only Git's existing LF/CRLF conversion notices. |

The frontend tests now use actual JSON `Response` objects: omission of an undefined
state survives serialization exactly as an absent field, rather than a test-only
exception. Fetch transport is scripted; React rendering uses jsdom.

## Reproduction

```powershell
docker build -f deploy/console-test.Dockerfile -t outreach-review-status-console .
docker run --rm --network none outreach-review-status-console
docker run --rm --network none outreach-review-status-console npm run build:demo
docker build -f deploy/test.Dockerfile -t outreach-review-status-python .
docker run --rm --network none outreach-review-status-python
```

Frontend image tested: `sha256:22f2314e6096b3e53b1a183c210e9402e1bbed081946331cd2854f5d6ea9b416`.
Python image tested: `sha256:96d5f87ca0e274d63c0194f9230bb2d957b2bc283c57d9cd637431ee62f3489b`.

The deliberate original-component break is reproducible without changing host files:

```powershell
git show f939d4a:console/src/pages/Review.tsx | docker run --rm -i --network none -e DEBUG_PRINT_LIMIT=1000 outreach-review-status-console sh -c 'cat > src/pages/Review.tsx && npm run test -- src/pages/Review.test.tsx -t "keeps actions disabled after a save"'
```

## Limits

No browser deployment, real storage, Google credentials, permissions, activation,
Gmail draft or send was exercised. Live behavior remains UNVERIFIED. The repository
has no standalone lint script; its TypeScript checks and build were used alongside
the whitespace check. This separate outreach repository has no `tools/ledger/cli.mjs`;
this file records the attempts without changing the cash-flow project's ledger.
