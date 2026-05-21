#!/usr/bin/env python3
"""Generate a file-to-issue mapping page for ansible/ansible.

Queries the GitHub API for open issues and PRs, extracts component information,
and generates a static HTML page with PatternFly theming.

For PRs: maps changed files directly.
For issues: parses the Component Name field and resolves keywords to actual
file paths by searching the repository tree.

Usage:
    python generate.py --repo ansible/ansible --output index.html
    python generate.py --data-repo ansible/ansible --deploy-repo jlmitch5/ansible --output index.html
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


def fetch_repo_tree(repo, branch="devel", token=None):
    """Fetch the full file tree from the repo to resolve component keywords."""
    url = f"https://api.github.com/repos/{repo}/git/trees/{branch}?recursive=1"
    data, _ = github_api(url, token)
    if isinstance(data, dict) and "tree" in data:
        return [
            item["path"]
            for item in data["tree"]
            if item["type"] == "blob"
        ]
    return []


def resolve_component_to_files(component, file_tree):
    """Resolve a component keyword (e.g., 'copy', 'apt') to actual file paths."""
    component = component.strip().lower()
    if not component:
        return []

    # If the component already looks like a file path, use it directly
    if "/" in component or component.endswith(".py"):
        matches = [f for f in file_tree if component in f.lower()]
        return matches[:5] if matches else [component]

    # Search for matching module, plugin, or doc files
    patterns = [
        f"lib/ansible/modules/{component}.py",
        f"lib/ansible/modules/{component}/",
        f"lib/ansible/plugins/action/{component}.py",
        f"lib/ansible/plugins/connection/{component}.py",
        f"lib/ansible/plugins/callback/{component}.py",
        f"lib/ansible/plugins/filter/{component}.py",
        f"lib/ansible/plugins/inventory/{component}.py",
        f"lib/ansible/plugins/lookup/{component}.py",
        f"lib/ansible/plugins/strategy/{component}.py",
        f"lib/ansible/plugins/shell/{component}.py",
        f"lib/ansible/plugins/vars/{component}.py",
        f"lib/ansible/plugins/cache/{component}.py",
        f"lib/ansible/plugins/test/{component}.py",
    ]

    matches = []
    for pattern in patterns:
        exact = [f for f in file_tree if f == pattern]
        if exact:
            matches.extend(exact)

    # Fuzzy match: find files containing the component name
    if not matches:
        fuzzy = [
            f for f in file_tree
            if f.startswith("lib/ansible/")
            and f.endswith(".py")
            and f"/{component}" in f.lower()
        ]
        matches = fuzzy[:5]

    # CLI tools
    cli_map = {
        "ansible-playbook": "lib/ansible/cli/playbook.py",
        "ansible-galaxy": "lib/ansible/cli/galaxy.py",
        "ansible-vault": "lib/ansible/cli/vault.py",
        "ansible-doc": "lib/ansible/cli/doc.py",
        "ansible-config": "lib/ansible/cli/config.py",
        "ansible-console": "lib/ansible/cli/console.py",
        "ansible-pull": "lib/ansible/cli/pull.py",
        "ansible-inventory": "lib/ansible/cli/inventory.py",
    }
    if component in cli_map:
        matches = [cli_map[component]]

    # Subsystem keywords
    subsystem_map = {
        "vault": ["lib/ansible/parsing/vault/__init__.py"],
        "jinja": ["lib/ansible/template/__init__.py"],
        "jinja2": ["lib/ansible/template/__init__.py"],
        "inventory": ["lib/ansible/inventory/manager.py"],
        "galaxy": ["lib/ansible/galaxy/api.py"],
        "become": ["lib/ansible/plugins/become/__init__.py"],
    }
    if component in subsystem_map:
        matches = subsystem_map[component]

    return matches if matches else [component]


STOP_WORDS = {
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "it", "as", "be", "was", "are",
    "not", "no", "yes", "all", "any", "can", "do", "has", "have", "had",
    "my", "i", "we", "you", "he", "she", "they", "this", "that", "these",
    "when", "where", "how", "what", "which", "who", "if", "then", "than",
    "so", "just", "also", "very", "too", "only", "does", "did", "will",
    "would", "should", "could", "may", "might", "must", "need", "etc",
    "eg", "ie", "see", "use", "using", "used", "module", "plugin",
    "n/a", "na", "none", "unknown", "other", "various", "multiple",
    # Issue template placeholder words
    "write", "short", "name", "rst", "file", "task", "feature", "below",
    "your", "best", "guess", "unsure", "tip", "cannot", "find", "please",
    "advised", "parts", "documentation", "hosted", "outside", "repository",
    "describes", "modules", "plugins", "officially", "supported", "core",
    "engineering", "team", "there", "good", "chance", "coming", "one",
    "collections", "maintained", "community", "case", "make", "sure",
    "under", "appropriate", "project", "instead", "org",
}


def extract_component(body):
    if not body:
        return []
    # Strip HTML comments before parsing
    clean = re.sub(r"<!--.*?-->", "", body, flags=re.DOTALL)
    match = re.search(r"### Component Name\s*\n+\s*(.+)", clean, re.IGNORECASE)
    if not match:
        return []
    raw = match.group(1).strip()
    # Stop at the next section header
    raw = re.split(r"\n\s*###", raw)[0]
    # Take only the first line (the actual component, not description text)
    raw = raw.split("\n")[0].strip()
    components = []
    for c in re.split(r"[,\s]+", raw):
        c = c.strip().lower().rstrip(".").strip("`")
        if len(c) < 2:
            continue
        if c in STOP_WORDS:
            continue
        # Skip things that look like HTML/markdown artifacts
        if c.startswith("<") or c.startswith("*") or c.startswith("["):
            continue
        if c.startswith("http"):
            continue
        components.append(c)
    return components


def get_pr_files(repo, pr_number, token=None):
    url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/files?per_page=100"
    files = paginate(url, token)
    return [f["filename"] for f in files if isinstance(f, dict)]


def generate_html(file_issues, data_repo, deploy_repo, generated_at):
    sorted_files = sorted(file_issues.items(), key=lambda x: -len(x[1]))
    total_files = len(sorted_files)
    total_issues = sum(len(v) for v in file_issues.values())

    rows = []
    for filepath, issues in sorted_files:
        issue_links = []
        seen = set()
        for issue in sorted(issues, key=lambda x: x["number"]):
            if issue["number"] in seen:
                continue
            seen.add(issue["number"])
            kind = "PR" if issue.get("is_pr") else "#"
            cls = "pf-v5-u-success-color-100" if issue.get("is_pr") else ""
            issue_links.append(
                f'<a href="{issue["url"]}" class="{cls}" target="_blank">'
                f'{kind}{issue["number"]}</a>'
            )
        file_url = f"https://github.com/{data_repo}/blob/devel/{filepath}"
        file_display = (
            f'<a href="{file_url}" target="_blank"><code>{filepath}</code></a>'
            if "/" in filepath
            else f"<code>{filepath}</code>"
        )
        rows.append(
            f"<tr>"
            f'<td data-label="File">{file_display}</td>'
            f'<td data-label="Count">{len(issue_links)}</td>'
            f'<td data-label="Issues/PRs">{" ".join(issue_links)}</td>'
            f"</tr>"
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{data_repo} — Issues by File</title>
  <link rel="stylesheet" href="https://unpkg.com/@patternfly/patternfly@5/patternfly.min.css">
  <style>
    body {{ background: var(--pf-v5-global--BackgroundColor--200); }}
    .app-header {{ background: var(--pf-v5-global--BackgroundColor--dark-100); color: white; padding: 1rem 2rem; }}
    .app-header h1 {{ margin: 0; font-size: 1.25rem; }}
    .app-header p {{ margin: 0.25rem 0 0; font-size: 0.85rem; opacity: 0.8; }}
    .app-content {{ max-width: 1400px; margin: 1rem auto; padding: 0 1rem; }}
    .stats {{ display: flex; gap: 2rem; margin-bottom: 1rem; flex-wrap: wrap; }}
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
    <h1>{data_repo} — Open Issues &amp; PRs by File</h1>
    <p>Sorted by issue count. Click column headers to re-sort. Use the search bar to filter.</p>
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
      Generated {generated_at} from
      <a href="https://github.com/{data_repo}">{data_repo}</a>
      — Powered by GitHub Actions
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
    parser.add_argument("--repo", default=None, help="Repo for both data and links (shorthand)")
    parser.add_argument("--data-repo", default="ansible/ansible", help="Repo to query for issues/PRs")
    parser.add_argument("--deploy-repo", default=None, help="Repo shown in footer (defaults to data-repo)")
    parser.add_argument("--output", default="index.html")
    parser.add_argument("--token", default=os.environ.get("GITHUB_TOKEN"))
    args = parser.parse_args()

    if args.repo:
        args.data_repo = args.repo
        if not args.deploy_repo:
            args.deploy_repo = args.repo
    if not args.deploy_repo:
        args.deploy_repo = args.data_repo

    print(f"Fetching file tree from {args.data_repo} (devel branch)...")
    file_tree = fetch_repo_tree(args.data_repo, "devel", args.token)
    print(f"  {len(file_tree)} files in tree")

    print(f"Fetching open issues from {args.data_repo}...")
    issues_url = f"https://api.github.com/repos/{args.data_repo}/issues?state=open&per_page=100"
    all_issues = paginate(issues_url, args.token)

    file_issues = defaultdict(list)
    pr_count = 0
    issue_count = 0
    unresolved = 0

    for item in all_issues:
        number = item["number"]
        url = item["html_url"]
        is_pr = "pull_request" in item

        if is_pr:
            pr_count += 1
            files = get_pr_files(args.data_repo, number, args.token)
            for f in files:
                file_issues[f].append(
                    {"number": number, "url": url, "is_pr": True}
                )
        else:
            issue_count += 1
            components = extract_component(item.get("body"))
            for comp in components:
                resolved_files = resolve_component_to_files(comp, file_tree)
                if resolved_files == [comp]:
                    unresolved += 1
                for f in resolved_files:
                    file_issues[f].append(
                        {"number": number, "url": url, "is_pr": False}
                    )

    print(f"Processed {issue_count} issues and {pr_count} PRs")
    print(f"Mapped to {len(file_issues)} unique files/components")
    if unresolved:
        print(f"  ({unresolved} components could not be resolved to file paths)")

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    html = generate_html(file_issues, args.data_repo, args.deploy_repo, generated_at)

    with open(args.output, "w") as f:
        f.write(html)
    print(f"Written to {args.output}")


if __name__ == "__main__":
    main()
