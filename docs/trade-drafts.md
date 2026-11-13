# Cloud trade drafts

Apply migration `0017_cloud_drafts_and_upload_ids` during backend deployment.
Drafts are separate from Trade records and never appear in analytics or history.

Authenticated endpoints under `/api/journals/:journal/drafts/:scope/` accept
`scope=new` or an existing trade ID owned by that journal. GET returns revision,
data and timestamp. PUT requires `{revision, data}`; DELETE requires `{revision}`.
Concurrent stale updates receive HTTP 409 with the latest draft. Deletion retains
a revision tombstone, preventing older devices from resurrecting discarded work.

Draft attachments use `images/:sha256/` PUT (multipart `file`) and GET (binary).
They are stored privately with the draft, behind the same journal ownership check;
GET responses use `private, no-store` and `nosniff`. No public image URLs or
Supabase credentials are sent to draft clients. Existing saved trade screenshots
continue to use their existing storage path. Limits: 1 MB JSON, 50 attachments,
5 MB per attachment, and 30 MB total attachment bytes per draft. Save/discard clears
attachments after pending synchronization finishes. Offline clear requests remain
in the local outbox until reconnection or reopening the draft.

The migration enables row-level security on the two new PostgreSQL tables, with
no Data API policies: application access runs through the owning Django database
role and the authenticated API. SQLite tests verify API ownership, revision,
validation, and idempotency behavior. This work does not alter live Supabase
storage buckets or publish database credentials.

Screenshot POST now accepts an optional `client_id`, unique within a trade.
Repeating that upload returns the same screenshot instead of creating duplicates.

Run `pytest tests/test_drafts.py tests/test_trade_api.py` with a test database.
