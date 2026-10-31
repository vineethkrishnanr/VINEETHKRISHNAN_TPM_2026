"""
Seed demo data for the Team Project Management API.

Usage (server must be running):
    pip install requests
    python seed_demo_data.py
    python seed_demo_data.py http://127.0.0.1:8000/api     # custom base URL

Safe to re-run: existing users are logged in instead of re-created,
and projects that already exist are skipped.
"""
import sys
from datetime import date, timedelta

import requests

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000/api").rstrip("/")
PASSWORD = "TpmDemo#2026"
TODAY = date.today()

USERS = [
    ("alice",   "Alice",   "Johnson"),
    ("bob",     "Bob",     "Mathew"),
    ("charlie", "Charlie", "Thomas"),
    ("diana",   "Diana",   "Joseph"),
    ("ethan",   "Ethan",   "George"),
]

# status path a new task has to follow (new tasks always start as todo)
PATH = {
    "todo": [],
    "in_progress": ["in_progress"],
    "in_review": ["in_progress", "in_review"],
    "done": ["in_progress", "in_review", "done"],
}

# (title, description, priority, assignee, due in N days, final status, [(commenter, text)])
PROJECTS = [
    {
        "name": "College ERP System",
        "description": "Student, faculty and fee management system for the college.",
        "owner": "alice",
        "members": ["bob", "charlie", "diana"],
        "tasks": [
            ("Design database schema", "ER diagram and MySQL tables", "high", "bob", -10, "done",
             [("bob", "Schema finished and reviewed."), ("alice", "Approved, good work.")]),
            ("Build student login module", "JWT login for students", "high", "charlie", 5, "in_review",
             [("charlie", "Ready for review.")]),
            ("Create fee payment API", "Endpoints for fee records and receipts", "urgent", "diana", -3, "in_progress",
             [("alice", "This one is overdue, please update the status.")]),
            ("Write unit tests", "Cover the attendance and marks modules", "medium", "bob", 12, "todo", []),
            ("Prepare project report", "Final documentation for submission", "low", None, 20, "todo", []),
        ],
    },
    {
        "name": "Mobile App Launch",
        "description": "Plan and ship version 1.0 of the mobile app.",
        "owner": "bob",
        "members": ["alice", "ethan"],
        "tasks": [
            ("Finalize UI mockups", "Home, profile and settings screens", "high", "alice", -7, "done",
             [("alice", "Mockups shared with the team.")]),
            ("Integrate push notifications", "Firebase setup for Android and iOS", "high", "ethan", 8, "in_progress",
             [("ethan", "Android working, iOS pending."), ("bob", "Thanks, keep me posted.")]),
            ("App store listing", "Screenshots, description and keywords", "medium", "alice", 15, "todo", []),
            ("Fix login crash on Android 12", "Crash reported by beta testers", "urgent", "ethan", -1, "in_review",
             [("bob", "Please attach the crash log.")]),
        ],
    },
    {
        "name": "Website Redesign",
        "description": "Refresh the company website with a modern layout.",
        "owner": "charlie",
        "members": ["diana", "ethan"],
        "tasks": [
            ("Homepage hero section", "New banner and call to action", "medium", "diana", 3, "in_progress",
             [("diana", "First draft is ready.")]),
            ("Optimize page load speed", "Compress images and lazy-load", "high", "ethan", 10, "todo", []),
            ("Contact form with validation", "Name, email and message fields", "low", "diana", -5, "done",
             [("charlie", "Tested on mobile too.")]),
        ],
    },
]


def die(msg):
    sys.exit(f"\nERROR: {msg}")


def call(method, path, token=None, **kwargs):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        r = requests.request(method, f"{BASE}{path}", headers=headers, timeout=15, **kwargs)
    except requests.ConnectionError:
        die(f"Cannot reach {BASE}. Is 'python manage.py runserver' running?")
    return r


def must(r, *ok):
    if r.status_code not in ok:
        die(f"{r.request.method} {r.url} -> {r.status_code}\n{r.text}")
    return r


def get_user(username, first, last):
    email = f"{username}@example.com"
    r = call("POST", "/auth/register/", json={
        "username": username, "email": email, "password": PASSWORD,
        "first_name": first, "last_name": last,
    })
    if r.status_code == 201:
        tokens = r.json()["tokens"]
        print(f"  created user  {username}")
    else:
        r = must(call("POST", "/auth/login/", json={"username": username, "password": PASSWORD}), 200)
        tokens = r.json()
        print(f"  user exists   {username} (logged in)")
    token = tokens["access"]
    me = must(call("GET", "/auth/me/", token), 200).json()
    return {"token": token, "id": me["id"], "email": email}


def main():
    print("Users")
    users = {u: get_user(u, f, l) for u, f, l in USERS}

    for p in PROJECTS:
        owner = users[p["owner"]]
        print(f"\nProject: {p['name']}")

        existing = must(call("GET", "/projects/", owner["token"], params={"search": p["name"]}), 200).json()
        if any(x["name"] == p["name"] for x in existing["results"]):
            print("  already exists, skipped")
            continue

        proj = must(call("POST", "/projects/", owner["token"],
                         json={"name": p["name"], "description": p["description"]}), 201).json()
        pid = proj["id"]
        print(f"  created project #{pid} (owner: {p['owner']})")

        for m in p["members"]:
            must(call("POST", f"/projects/{pid}/members/", owner["token"],
                      json={"email": users[m]["email"]}), 201)
            print(f"  added member  {m}")

        for title, desc, prio, assignee, due, final, comments in p["tasks"]:
            body = {
                "title": title, "description": desc, "priority": prio,
                "due_date": (TODAY + timedelta(days=due)).isoformat(),
                "assignee": users[assignee]["id"] if assignee else None,
            }
            task = must(call("POST", f"/projects/{pid}/tasks/", owner["token"], json=body), 201).json()
            for step in PATH[final]:
                must(call("PATCH", f"/projects/{pid}/tasks/{task['id']}/", owner["token"],
                          json={"status": step}), 200)
            for who, text in comments:
                must(call("POST", f"/projects/{pid}/tasks/{task['id']}/comments/",
                          users[who]["token"], json={"body": text}), 201)
            print(f"  task #{task['id']:<3} [{final:<11}] {title}")

    print("\nDone. Demo users all use the password:", PASSWORD)
    print("Usernames:", ", ".join(u for u, _, _ in USERS))


if __name__ == "__main__":
    main()