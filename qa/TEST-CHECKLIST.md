# Phase 35 — Production QA Checklist

Phase 35 adds QA tooling only. Runtime bot behavior is intentionally unchanged.

## Automated checks

Run from the project root:

```bash
python tools/run_qa.py
```

The suite checks:
- required files
- Python compilation
- command registration
- message-size security guard
- result cache hit/single-flight behavior
- queue concurrency/FIFO behavior
- daily rate-limit enforcement
- maintenance/status controls

## Live deployment checks

After deploying to Render, verify manually:

1. `/start` and `/help`
2. Single TeraBox link → direct result without asking the user to retry
3. Three unique links in one message → three results
4. Duplicate link in one message → duplicate is ignored
5. Same link from two users close together → one upstream resolve, both receive result
6. 2 simultaneous users → both complete; concurrency stays within the configured limit
7. Queue status → `/queue`
8. Daily quota → `/mylimit`
9. History/profile → `/history`, `/profile`
10. Admin dashboard → `/admin`
11. Analytics → `/analytics`
12. Broadcast → `/broadcast`
13. System status → `/status`
14. Maintenance toggle → `/maintenance on` then `/maintenance off`
15. Render redeploy/restart → databases persist; in-memory queue/cache reset safely
16. API timeout simulation → internal retry, no user-facing verification error for a temporary API timeout

## Release rule

Do not proceed to the next phase until the live checks above pass on the deployed Render service.
