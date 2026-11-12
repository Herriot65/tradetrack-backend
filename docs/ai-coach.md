# AI trading coach

The frontend `/coach` page uses the selected journal. Chat, suggested prompts,
and arbitrary scheduled coaching instructions share one read-only agent.
Persistent coaching memory is intentionally excluded. Chat context lives only
in the open page; task instructions and execution results are stored in Django.
Previous task results are never automatically passed to the model.

## Enable

1. Apply migrations with `python manage.py migrate`. Migration `0016` merges
   the existing coach migration with main’s rich-note migrations; databases
   that already applied coach `0014` can upgrade without recreating its tables.
2. Set `OPENAI_API_KEY` in the backend's secret settings. Never set a `VITE_`
   variable for this key. A paid API account is required; ChatGPT subscriptions
   do not include API usage.
3. Optionally set `COACH_MODEL` (default `gpt-4.1-mini`) to a model supporting
   Chat Completions, function tools, and image inputs when screenshots are used.
4. Allow outbound HTTPS to `api.openai.com`. In the managed development
   environment this domain must be added to the network allowlist before live
   provider calls will work. No key or provider access is supplied by this change.
5. Restart the backend. The UI's connection status indicates whether a key is
   configured, not whether provider credentials/billing have been verified.
6. Install a cron job or platform scheduler to invoke this command every minute
   against the same production database and environment as the web service:

   ```sh
   python manage.py run_coach_tasks
   ```

   Example crontab (adjust paths to your deployment):

   ```cron
   * * * * * cd /app && /app/.venv/bin/python manage.py run_coach_tasks
   ```

No operating-system or production schedule is installed automatically. Tasks
can be saved before AI setup; attempted runs produce a visible setup error.
Results appear under Scheduled tasks → View history; email, push notifications,
and live-market integrations are not included.

## Data and execution

- JWT authentication and journal ownership are enforced before chat, task CRUD,
  run history, and manual executions. Models never receive a selectable user ID.
- `get_statistics` calls the existing `get_dashboard_summary` and journal
  break-even threshold. Statistics use all matching trades, even if the model
  only requests a sample of trade notes.
- `get_trades` reads the current structured note document, including titled
  sections, as bounded plain text. Legacy notes are used only when no rich
  document exists. It includes canonical trade status and current setup fields,
  while excluding styling and image-layout metadata. It returns up to 30 records per call, with at most six provider
  turns and eight calls per turn. Notes are bounded; the model must acknowledge
  insufficient evidence rather than generalize beyond it. The period uses entry
  timestamps; rolling 7/30 days include today in the chosen timezone.
- Screenshot analysis is opt-in, with up to three images per response. Only
  HTTPS image URLs on the configured Supabase host are passed to the provider.
  Image evidence uses the current note-section placement when available.
  Private storage must provide URLs that the provider can actually access.
- The provider receives the prompt, selected configuration, at most twelve
  conversation messages, and tool-selected journal evidence. User data is not
  used as system instructions. Tools cannot mutate trading records.
- Only explicitly configured report sections are requested; an empty selection
  lets the coach answer the question naturally. Goals are supplied as context,
  not a persistent goal-management system.

## Scheduling semantics

Tasks are once, daily, weekly, or monthly, anchored to their start date and local
wall-clock time. Weekly tasks use the start date's weekday. Monthly tasks use its
day, clamped to month-end in shorter months. IANA timezones follow daylight-saving
changes. A nonexistent local time moves forward through the DST gap; repeated
hours run once at their first occurrence.

Production uses PostgreSQL row locks to claim executions. The schedule advances
before calling the provider, so overlapping workers cannot bill twice for the
same due execution. Missed occurrences collapse into one run with current data.
Manual execution does not advance the schedule and can run a paused task. Runs
are synchronous in the web request/command; allow up to five minutes in your
web server and reverse proxy. The default single-process command handles up to
100 due tasks per invocation. A queue worker is a future scaling improvement.

Failures remain visible and are not immediately retried. A process killed after
claiming a task may leave a running record; a subsequent attempt after ten
minutes marks it failed. This favors avoiding duplicate paid requests over
transparent retries. On a subsequent scheduled occurrence the task runs again.
SQLite is suitable for local development, not concurrent production scheduling.

AI generation (chat POST and Run now) is limited to 30 requests/hour/user using DRF's cache
throttle; connection checks and task management do not consume that allowance.
Each journal can hold 20 tasks. Use a shared Django cache for consistent
limits across web processes. These are guardrails, not a monthly spending cap.
Set provider budget alerts/limits before enabling broad paid usage.

## API

All routes start at `/api/journals/{journal_id}/coach/`:

| Route | Method | Purpose |
| --- | --- | --- |
| `chat/` | GET | Configuration status (never returns the key) |
| `chat/` | POST | Instructions, output configuration, session history |
| `tasks/` | GET / POST | List or create arbitrary coaching tasks |
| `tasks/{id}/` | GET / PATCH / DELETE | Read, edit, pause, resume, or delete |
| `tasks/{id}/run/` | POST | Run now and save the result |
| `tasks/{id}/history/` | GET | Latest twenty execution results |

Deleting a task deletes its execution history. Deleting a journal cascades to
its coaching tasks. No external calendar or ChatGPT task automation is created.

## Validation

`pytest tests/test_coach.py` covers isolation, existing statistics, tool calls,
configuration, task CRUD, explicit provider errors, scheduling, and DST.
Frontend `npm run test:coach` exercises the actual page with mocked API replies;
it never makes paid AI calls. Supply `PLAYWRIGHT_MODULE` when Playwright is
installed outside the frontend package. Live model quality, billing, provider
image access and production cron wiring require validation after setup.

## Trader experience

The coach starts with six editable prompts: weekly review, session preparation,
loss analysis, risk discipline, reflection, and goal progress. Shortcuts prepare a
question for the trader to review before sending; they do not run paid requests
on click. Today, 7-day, 30-day, and custom periods are visible above the chat.

`configuration.trade_status` accepts `all`, `closed`, `WIN`, `LOSS`, `BE`, or
`OPEN`. The same server-side filter applies to trade evidence, existing
statistics, and screenshots. Status classification uses the journal's existing
break-even rules. Recorded risk percentage, risk amount, and capital basis are
available to the read-only agent for discipline questions.

The trade picker searches only the selected journal. Picking a trade clears
conflicting filters and uses its entry date in the account timezone; clearing
the selection restores the previous scope. Supporting trade citations open the
existing read-only rich-note and screenshot viewer.

Answers can be copied, simplified with an editable follow-up, or turned into a
next-step question. Conversations can be downloaded as plain text. They are not
stored in browser storage or in the database; a new-chat confirmation helps avoid
accidental loss. Downloaded files contain personal journal information.

A failed request keeps the question for retry. Stop waiting abandons the browser
request and preserves the draft; it cannot guarantee cancellation of a request
already executing at the provider, and the UI states that clearly.

Task templates cover session preparation, end-of-day reflection, weekly
discipline, and a full monthly report. Instructions remain editable. A schedule
preview shows the weekday or month-day, time, and timezone. Data/output settings
are collapsed by default. Run now opens its result immediately; task history
still provides saved results. Provider setup details are kept out of the trader
flow; administrators should follow the Enable section above.
