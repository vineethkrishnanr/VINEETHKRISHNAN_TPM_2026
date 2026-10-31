# Team Project Management API (TPM 2026)

A backend REST API for managing team projects and tasks, built with **Django, Django REST Framework, MySQL 8 and JWT authentication**.

Features: register / login / refresh with JWT, projects and members (owner-managed), tasks with a validated status workflow, comments, a per-task activity log, a project dashboard, assignment notifications (Django signals) and soft delete.

## 1. Prerequisites

- Python 3.10+
- MySQL 8.0.16+ (CHECK constraints are enforced from 8.0.16)
- [Postman](https://www.postman.com/downloads/)

## 2. Setup

```bash
python -m venv venv
venv\Scripts\activate           # Windows
source venv/bin/activate        # macOS / Linux
pip install -r requirements.txt
```

Create the database (MySQL Workbench or the `mysql` shell):

```sql
CREATE DATABASE tpm_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

Create your `.env` from the template and fill in the values:

```bash
copy .env.example .env          # Windows
cp .env.example .env            # macOS / Linux
```

Generate a secret key and paste it into `SECRET_KEY`:

```bash
python -c "from django.core.management.utils import get_random_secret_key as g; print(g())"
```

Run migrations and start the server:

```bash
python manage.py migrate
python manage.py runserver
```

The API is now at `http://127.0.0.1:8000/api/`.

## 3. Test the API with Postman

1. Keep the server running.
2. In Postman choose **Import** and select `TPM_API.postman_collection.json` (in the project root).
3. Click the collection, then **Run**, then **Run TPM API**. All requests run in order and every test should pass.

The collection registers its own test users, so no data needs to exist beforehand. It saves tokens and IDs automatically. To try requests one by one, run **1. Auth -> Register user 1** and **Login** first, then any other request.

| Folder | Covers |
|---|---|
| 1. Auth | register, login, refresh, current user, error cases |
| 2. Projects | create, list, search, get, update, not-found |
| 3. Members | add, list, duplicates, owner cannot be removed |
| 4. Tasks | create, filters, search, ordering, pagination, status workflow, dashboard |
| 5. Comments & Activity | add, list, delete, audit trail |
| 6. Permissions | non-owner members get 403 |
| 7. Delete & cleanup | soft delete, remove member, delete project |

### Optional: demo data

With the server running:

```bash
pip install requests
python seed_demo_data.py
```

This creates users `alice`, `bob`, `charlie`, `diana`, `ethan` (password `TpmDemo#2026`) with three projects, tasks, comments and activity. Log in as any of them from Postman.

## 4. Tests

```bash
python manage.py test
```

20 `APITestCase` tests. Django creates a temporary `test_tpm_db` database, so the MySQL user needs the CREATE privilege.

## 5. Endpoints

Base path `/api/`. Everything except register, login and refresh needs `Authorization: Bearer <access>`.

| Method | URL | Notes |
|---|---|---|
| POST | `/auth/register/` | username, email, password -> user + tokens |
| POST | `/auth/login/` | username, password -> access + refresh |
| POST | `/auth/refresh/` | refresh -> new access |
| GET | `/auth/me/` | current user |
| GET, POST | `/projects/` | only my projects; creator becomes owner |
| GET, PUT, PATCH, DELETE | `/projects/{id}/` | write/delete: owner only |
| GET | `/projects/{id}/dashboard/` | counts by status, overdue, tasks per member |
| GET, POST | `/projects/{id}/members/` | POST (owner only): `{"email": "..."}` |
| DELETE | `/projects/{id}/members/{user_id}/` | owner only; owner cannot be removed |
| GET, POST | `/projects/{id}/tasks/` | filters, sorting, search, pagination |
| GET, PUT, PATCH, DELETE | `/projects/{id}/tasks/{task_id}/` | DELETE = soft delete |
| GET, POST | `/projects/{id}/tasks/{task_id}/comments/` | |
| DELETE | `/projects/{id}/tasks/{task_id}/comments/{id}/` | author or owner |
| GET | `/projects/{id}/tasks/{task_id}/activity/` | audit trail |

### Task list query parameters

`?status=todo&priority=high&assignee=3&search=login&ordering=due_date&due_before=2026-12-31&page=2&page_size=20`

- `ordering`: `due_date`, `-due_date`, `created_at`, `updated_at`, `title`
- Paginated response: `{count, next, previous, results}`

### Status transitions

```
todo        -> in_progress
in_progress -> todo | in_review | done
in_review   -> in_progress | done
done        -> in_progress   (re-open)
```

New tasks always start as `todo`. Invalid moves return 400.

### Error format (all errors)

```json
{"error": {"code": "validation_error", "status": 400, "message": "Invalid input.", "details": {"status": ["..."]}}}
```

## 6. Design notes

- **Visibility:** project queries are filtered by membership; non-members get 404 so a project's existence is not leaked.
- **Permissions:** only the owner can edit or delete a project and manage members; only the owner or task creator can delete a task; only the author or owner can delete a comment.
- **Database:** unique (project, user) membership; CHECK constraints on status, priority, role and soft-delete consistency; composite indexes on (project, status), (project, assignee), (project, due_date) and (project, is_deleted).
- **Soft delete:** `Task.objects` hides deleted rows, `Task.all_objects` includes them (`is_deleted`, `deleted_at`). The admin still shows deleted tasks.
- **Notifications:** `projects/signals.py` (pre_save + post_save on `Task`) calls `projects/notifications.py`, which logs and emails whenever the assignee changes. Emails print in the terminal (console backend).
- **Activity log:** creation, field changes, status changes, assignment, comments and deletion are stored in `TaskActivity`.

## 7. Project structure

```
TASK_AND_PROJECT_MANAGER/   settings, urls, error handler, pagination
projects/                   models, serializers, views, permissions, filters, signals, tests
TPM_API.postman_collection.json   Postman collection
seed_demo_data.py           optional demo data script
```