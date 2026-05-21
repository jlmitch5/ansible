# Ansible Triage Bot (GitHub Actions)

This directory contains the GitHub Actions-based replacement for
[ansibotmini](https://github.com/ansible/ansibotmini), the triage bot that
manages issues and pull requests on `ansible/ansible`.

## Why

ansibotmini runs as a Python daemon on a dedicated EC2 instance (t2.xlarge,
$145/mo) polling GitHub every 5 minutes. All of its functionality can be
replicated with event-driven GitHub Actions at zero cost on public repos, with
faster response times and no infrastructure to maintain.

| | ansibotmini | GitHub Actions |
|---|---|---|
| **Cost** | $145/mo ($1,740/yr) | $0 |
| **Response time** | ~5 min polling delay | Instant (event-driven) |
| **Infrastructure** | EC2 instance + EBS | GitHub-managed |
| **Maintenance** | Custom Python daemon | Standard YAML workflows |
| **Reliability** | Single instance | GitHub SLA |

## Workflows

All workflow files live in `.github/workflows/` and are prefixed with `bot-`.

### bot-lock-threads.yml

**Purpose:** Lock closed issues and PRs after 14 days of inactivity.

- **Trigger:** Daily at 03:17 UTC + manual dispatch
- **How:** Uses [dessant/lock-threads](https://github.com/dessant/lock-threads)
- **Config:** 14-day inactivity threshold, lock reason: `resolved`

### bot-unsigned-commits.yml

**Purpose:** Warn contributors when a PR contains unsigned commits.

- **Trigger:** `pull_request` opened or updated
- **How:** Checks each commit's `verification.verified` field via GitHub API.
  Posts or updates a warning comment listing the unsigned commits.
- **Idempotent:** Uses a hidden HTML marker (`<!-- ansibot-unsigned-commits -->`)
  to find and update existing comments instead of posting duplicates.

### bot-label-components.yml

**Purpose:** Automatically label PRs and issues based on which ansible-core
components they affect.

- **Trigger:** `pull_request_target` opened/updated (for PRs),
  `issues` opened/edited (for issues)
- **How:**
  - **PRs:** Reads the list of changed files and matches against glob patterns
    in `component-labels.yml`
  - **Issues:** Parses the `### Component Name` field from the issue template
    and maps keywords to labels via the `keywords` section of `component-labels.yml`
- **Config:** `.github/ansibot/component-labels.yml`
- **Auto-creates labels** if they don't exist yet

### bot-collection-redirect.yml

**Purpose:** Close issues about components that have moved to Ansible collections,
and redirect the reporter to the correct repository.

- **Trigger:** `issues` opened
- **How:** Parses the component name from the issue body and checks it against
  `collection-redirects.yml`. If a match is found, posts a redirect comment,
  adds the `collection_redirect` label, and closes the issue.
- **Config:** `.github/ansibot/collection-redirects.yml`

### bot-ci-failure-comment.yml

**Purpose:** Post detailed CI failure information on PRs when Azure Pipelines
builds fail.

- **Trigger:** Every 5 minutes (cron) + manual dispatch
- **How:** Queries the Azure DevOps REST API for recently failed builds,
  fetches the build timeline and logs, and posts a formatted comment on the
  associated PR with failure details.
- **Requires:** `AZURE_DEVOPS_PAT` repository secret (Personal Access Token
  with Build read scope). The workflow gracefully skips if this secret is not
  configured.
- **Deduplication:** Uses hidden markers (`<!-- ansibot-ci-{buildId} -->`) to
  avoid posting duplicate comments for the same build.

### bot-commands.yml

**Purpose:** Respond to `@ansibot` commands in issue and PR comments.

- **Trigger:** `issue_comment` created (only when body contains `@ansibot`)
- **Supported commands:**
  - `@ansibot component =path/to/file` — add the component label for that path
  - `@ansibot !component =path/to/file` — remove the component label
  - `@ansibot label +label_name` — add a label
  - `@ansibot label -label_name` — remove a label
- **Feedback:** Adds an :eyes: reaction to acknowledge the command was processed

### bot-byfile-pages.yml

**Purpose:** Generate and deploy a static site mapping ansible-core files to
their associated open issues and PRs.

- **Trigger:** Every 6 hours (cron) + manual dispatch
- **How:** Runs `generate.py` to query the GitHub API, then deploys the output
  to GitHub Pages via `actions/deploy-pages`
- **Output:** A PatternFly-themed HTML page with search/filter and sortable
  columns. Replaces the plain HTML at `ansibotmini.eng.ansible.com/byfile.html`.
- **Generator:** `.github/pages/byfile/generate.py`

## Configuration Files

### component-labels.yml

Maps file path globs to label names (for PR labeling) and component keywords
to labels (for issue labeling). Edit this file to add new components or adjust
label mappings.

### collection-redirects.yml

Maps old component names to their new collection homes. Each entry has:
- `collection` — the fully-qualified collection name (e.g., `amazon.aws`)
- `repo` — the GitHub URL of the collection repository

Source data: [ansible-community/ansible-build-data](https://github.com/ansible-community/ansible-build-data)

### comment-templates/

Markdown templates used by the bot comments. These are reference copies —
the actual comment text is currently inline in the workflow scripts for
simplicity.

## Setup

1. **Enable GitHub Pages** on the repository (Settings → Pages → Source: GitHub Actions)
2. **Add the `AZURE_DEVOPS_PAT` secret** (Settings → Secrets → Actions) for CI
   failure comments. This is optional — all other workflows work without it.
3. **Create initial labels** — workflows auto-create labels on first use, or
   you can pre-create them for consistent colors/descriptions.

## Testing

To test on a fork:

1. Fork `ansible/ansible`
2. Copy the `.github/ansibot/` and `.github/pages/` directories
3. Copy the `bot-*.yml` workflow files
4. Open test issues and PRs to verify each workflow triggers correctly
5. Check the Actions tab for workflow run results
6. Enable GitHub Pages to verify the byfile site

## Migration from ansibotmini

Once all workflows are verified on the fork:

1. Open a PR to `ansible/ansible` with these files
2. After merge, verify workflows run correctly on the main repo
3. Retire the `collectionbot` EC2 instance (i-0f517a4f128b6fe4a, us-east-2)
4. Update DNS for `ansibotmini.eng.ansible.com` to point to GitHub Pages
