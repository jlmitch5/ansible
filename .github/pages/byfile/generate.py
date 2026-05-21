#!/usr/bin/env python3
"""Generate a file-to-issue mapping page for ansible/ansible.

Queries the GitHub API for open issues and PRs, extracts component information,
and generates a static HTML page with PatternFly theming.

Usage:
    python generate.py --repo ansible/ansible --output index.html
    python generate.py --repo jlmitch5/ansible --output index.html --token $GITHUB_TOKEN
"""

import argparse
import json
import os
import re
import sys
import urllib.request
import urllib.error
from collections import defaultdict
from datetime import datetime, timezone


def github_api(url, token=None):
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())
            link = resp.headers.get("Link", "")
            return data, link
    except urllib.error.HTTPError as e:
        print(f"API error {e.code}: {url}", file=sys.stderr)
        return [], ""


def paginate(url, token=None):
    results = []
    while url:
        data, link = github_api(url, token)
        if isinstance(data, list):
            results.extend(data)
        else:
            results.append(data)
        url = None
        if link:
            for part in link.split(","):
                if 'rel="next"' in part:
                    url = part.split("<")[1].split(">")[0]
    return results


def extract_component(body):
    if not body:
        return []
    match = re.search(r"### Component Name\s*\n+\s*(.+)", body, re.IGNORECASE)
    if not match:
        return []
    raw = match.group(1).strip()
    return [c.strip().lower() for c in re.split(r"[,\s]+", raw) if c.strip()]


def get_pr_files(repo, pr_number, token=None):
    url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/files?per_page=100"
    files = paginate(url, token)
    return [f["filename"] for f in files if isinstance(f, dict)]


def generate_html(file_issues, repo, generated_at):
    sorted_files = sorted(file_issues.items(), key=lambda x: -len(x[1]))
    total_files = len(sorted_files)
    total_issues = sum(len(v) for v in file_issues.values())

    rows = []
    for filepath, issues in sorted_files:
        issue_links = []
        for issue in sorted(issues, key=lambda x: x["number"]):
            kind = "PR" if issue.get("is_pr") else "#"
            cls = "pf-v5-u-success-color-100" if issue.get("is_pr") else ""
            issue_links.append(
                f'<a href="{issue["url"]}" class="{cls}" target="_blank">'
                f'{kind}{issue["number"]}</a>'
            )
        rows.append(
            f"<tr>"
            f'<td data-label="File"><code>{filepath}</code></td>'
            f'<td data-label="Count">{len(issues)}</td>'
            f'<td data-label="Issues/PRs">{" ".join(issue_links)}</td>'
            f"</tr>"
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>ansible/ansible — Issues by File</title>
  <link rel="stylesheet" href="https://unpkg.com/@patternfly/patternfly@5/patternfly.min.css">
  <style>
    body {{ background: var(--pf-v5-global--BackgroundColor--200); }}
    .app-header {{ background: var(--pf-v5-global--BackgroundColor--dark-100); color: white; padding: 1rem 2rem; }}
    .app-header h1 {{ margin: 0; font-size: 1.25rem; }}
    .app-content {{ max-width: 1200px; margin: 1rem auto; padding: 0 1rem; }}
    .stats {{ display: flex; gap: 2rem; margin-bottom: 1rem; }}
    .stat {{ background: white; padding: 1rem; border-radius: 4px; box-shadow: var(--pf-v5-global--BoxShadow--sm); }}
    .stat-value {{ font-size: 1.5rem; font-weight: bold; color: var(--pf-v5-global--primary-color--100); }}
    .stat-label {{ font-size: 0.85rem; color: var(--pf-v5-global--Color--200); }}
    #search {{ width: 100%; padding: 0.5rem; margin-bottom: 1rem; font-size: 1rem;
               border: 1px solid var(--pf-v5-global--BorderColor--100); border-radius: 4px; }}
    table {{ width: 100%; background: white; border-collapse: collapse;
            box-shadow: var(--pf-v5-global--BoxShadow--sm); border-radius: 4px; }}
    th {{ background: var(--pf-v5-global--BackgroundColor--100); text-align: left;
         padding: 0.75rem 1rem; border-bottom: 2px solid var(--pf-v5-global--BorderColor--100);
         cursor: pointer; user-select: none; }}
    th:hover {{ background: var(--pf-v5-global--BackgroundColor--200); }}
    td {{ padding: 0.5rem 1rem; border-bottom: 1px solid var(--pf-v5-global--BorderColor--100); }}
    td a {{ margin-right: 0.25rem; }}
    .footer {{ text-align: center; padding: 1rem; color: var(--pf-v5-global--Color--200); font-size: 0.85rem; }}
    .hidden {{ display: none; }}
  </style>
</head>
<body>
  <div class="app-header">
    <h1>ansible/ansible — Open Issues &amp; PRs by File</h1>
  </div>
  <div class="app-content">
    <div class="stats">
      <div class="stat">
        <div class="stat-value">{total_files}</div>
        <div class="stat-label">Files with issues</div>
      </div>
      <div class="stat">
        <div class="stat-value">{total_issues}</div>
        <div class="stat-label">Total issue/PR references</div>
      </div>
    </div>
    <input type="text" id="search" placeholder="Filter by filename..." autocomplete="off">
    <table>
      <thead>
        <tr>
          <th onclick="sortTable(0)">File</th>
          <th onclick="sortTable(1)">Count</th>
          <th>Issues / PRs</th>
        </tr>
      </thead>
      <tbody>
        {"".join(rows)}
      </tbody>
    </table>
    <div class="footer">
      Generated {generated_at} from <a href="https://github.com/{repo}">{repo}</a>
      — Replaces <a href="https://ansibotmini.eng.ansible.com/byfile.html">ansibotmini byfile</a>
    </div>
  </div>
  <script>
    const search = document.getElementById('search');
    const rows = document.querySelectorAll('tbody tr');
    search.addEventListener('input', () => {{
      const q = search.value.toLowerCase();
      rows.forEach(row => {{
        const file = row.cells[0].textContent.toLowerCase();
        row.classList.toggle('hidden', !file.includes(q));
      }});
    }});
    function sortTable(col) {{
      const tbody = document.querySelector('tbody');
      const rowsArr = Array.from(rows);
      const isNum = col === 1;
      rowsArr.sort((a, b) => {{
        const av = isNum ? parseInt(a.cells[col].textContent) : a.cells[col].textContent;
        const bv = isNum ? parseInt(b.cells[col].textContent) : b.cells[col].textContent;
        return isNum ? bv - av : av.localeCompare(bv);
      }});
      rowsArr.forEach(r => tbody.appendChild(r));
    }}
  </script>
</body>
</html>"""


def main():
    parser = argparse.ArgumentParser(description="Generate byfile issue mapping")
    parser.add_argument("--repo", default="ansible/ansible")
    parser.add_argument("--output", default="index.html")
    parser.add_argument("--token", default=os.environ.get("GITHUB_TOKEN"))
    args = parser.parse_args()

    print(f"Fetching open issues from {args.repo}...")
    issues_url = f"https://api.github.com/repos/{args.repo}/issues?state=open&per_page=100"
    all_issues = paginate(issues_url, args.token)

    file_issues = defaultdict(list)
    pr_count = 0
    issue_count = 0

    for item in all_issues:
        number = item["number"]
        url = item["html_url"]
        is_pr = "pull_request" in item

        if is_pr:
            pr_count += 1
            files = get_pr_files(args.repo, number, args.token)
            for f in files:
                file_issues[f].append(
                    {"number": number, "url": url, "is_pr": True}
                )
        else:
            issue_count += 1
            components = extract_component(item.get("body"))
            for comp in components:
                file_issues[comp].append(
                    {"number": number, "url": url, "is_pr": False}
                )

    print(f"Processed {issue_count} issues and {pr_count} PRs")
    print(f"Mapped to {len(file_issues)} unique files/components")

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    html = generate_html(file_issues, args.repo, generated_at)

    with open(args.output, "w") as f:
        f.write(html)
    print(f"Written to {args.output}")


if __name__ == "__main__":
    main()
