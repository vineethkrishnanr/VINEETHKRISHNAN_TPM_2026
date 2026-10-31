from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core import mail
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from .models import Project, ProjectMember, Task, TaskActivity

User = get_user_model()
PASSWORD = "StrongPass#2026"


class BaseTestCase(APITestCase):
    def setUp(self):
        self.owner = User.objects.create_user("owner", "owner@example.com", PASSWORD)
        self.alice = User.objects.create_user("alice", "alice@example.com", PASSWORD)
        self.bob = User.objects.create_user("bob", "bob@example.com", PASSWORD)
        self.outsider = User.objects.create_user("outsider", "out@example.com", PASSWORD)

        self.project = self.make_project(self.owner, "Alpha")
        ProjectMember.objects.create(project=self.project, user=self.alice)
        ProjectMember.objects.create(project=self.project, user=self.bob)

    @staticmethod
    def make_project(owner, name):
        project = Project.objects.create(name=name, owner=owner)
        ProjectMember.objects.create(project=project, user=owner, role=ProjectMember.Role.OWNER)
        return project

    def make_task(self, **kwargs):
        defaults = {"project": self.project, "title": "Task", "created_by": self.owner}
        defaults.update(kwargs)
        return Task.objects.create(**defaults)

    def login(self, user):
        self.client.force_authenticate(user=user)

    def tasks_url(self, project=None):
        return reverse("task-list", kwargs={"project_pk": (project or self.project).pk})

    def task_url(self, task):
        return reverse("task-detail", kwargs={"project_pk": task.project_id, "pk": task.pk})


class AuthTests(APITestCase):
    def test_register_login_and_refresh(self):
        payload = {"username": "newuser", "email": "new@example.com", "password": PASSWORD}
        res = self.client.post(reverse("auth-register"), payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertIn("access", res.data["tokens"])
        self.assertNotIn("password", res.data["user"])

        res = self.client.post(
            reverse("auth-login"), {"username": "newuser", "password": PASSWORD}, format="json"
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        access, refresh = res.data["access"], res.data["refresh"]

        res = self.client.get(reverse("auth-me"), HTTP_AUTHORIZATION=f"Bearer {access}")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["username"], "newuser")

        res = self.client.post(reverse("auth-refresh"), {"refresh": refresh}, format="json")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn("access", res.data)

    def test_register_duplicate_email_returns_consistent_error(self):
        User.objects.create_user("x", "dup@example.com", PASSWORD)
        res = self.client.post(
            reverse("auth-register"),
            {"username": "y", "email": "DUP@example.com", "password": PASSWORD},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data["error"]["code"], "validation_error")
        self.assertIn("email", res.data["error"]["details"])

    def test_unauthenticated_request_is_rejected(self):
        res = self.client.get(reverse("project-list"))
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(res.data["error"]["status"], 401)


class ProjectAccessTests(BaseTestCase):
    def test_user_only_sees_projects_they_belong_to(self):
        self.make_project(self.outsider, "Secret")
        self.login(self.alice)
        res = self.client.get(reverse("project-list"))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual([p["name"] for p in res.data["results"]], ["Alpha"])

    def test_non_member_gets_404_on_project_and_tasks(self):
        self.login(self.outsider)
        res = self.client.get(reverse("project-detail", kwargs={"pk": self.project.pk}))
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)
        res = self.client.get(self.tasks_url())
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)
        res = self.client.post(self.tasks_url(), {"title": "x"}, format="json")
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_creating_project_makes_creator_owner_member(self):
        self.login(self.alice)
        res = self.client.post(reverse("project-list"), {"name": "Beta"}, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        membership = ProjectMember.objects.get(project_id=res.data["id"], user=self.alice)
        self.assertEqual(membership.role, ProjectMember.Role.OWNER)

    def test_only_owner_can_update_or_delete_project(self):
        url = reverse("project-detail", kwargs={"pk": self.project.pk})
        self.login(self.alice)
        self.assertEqual(self.client.patch(url, {"name": "Hacked"}, format="json").status_code, 403)
        self.assertEqual(self.client.delete(url).status_code, 403)
        self.login(self.owner)
        self.assertEqual(self.client.patch(url, {"name": "Renamed"}, format="json").status_code, 200)

    def test_owner_manages_members(self):
        url = reverse("project-members", kwargs={"project_pk": self.project.pk})
        payload = {"email": "out@example.com"}

        self.login(self.alice)  # regular member cannot add
        self.assertEqual(self.client.post(url, payload, format="json").status_code, 403)

        self.login(self.owner)
        res = self.client.post(url, payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(self.client.post(url, payload, format="json").status_code, 400)  # duplicate

        detail = reverse(
            "project-member-detail", kwargs={"project_pk": self.project.pk, "user_id": self.outsider.pk}
        )
        self.assertEqual(self.client.delete(detail).status_code, status.HTTP_204_NO_CONTENT)

        owner_detail = reverse(
            "project-member-detail", kwargs={"project_pk": self.project.pk, "user_id": self.owner.pk}
        )
        self.assertEqual(self.client.delete(owner_detail).status_code, 400)

    def test_removing_member_unassigns_their_tasks(self):
        task = self.make_task(assignee=self.alice)
        self.login(self.owner)
        url = reverse(
            "project-member-detail", kwargs={"project_pk": self.project.pk, "user_id": self.alice.pk}
        )
        self.assertEqual(self.client.delete(url).status_code, 204)
        task.refresh_from_db()
        self.assertIsNone(task.assignee)


class TaskTests(BaseTestCase):
    def test_create_task_and_assignee_must_be_member(self):
        self.login(self.owner)
        ok = self.client.post(
            self.tasks_url(),
            {"title": "Build API", "priority": "high", "assignee": self.alice.pk, "due_date": "2030-01-01"},
            format="json",
        )
        self.assertEqual(ok.status_code, status.HTTP_201_CREATED)
        self.assertEqual(ok.data["status"], "todo")
        self.assertEqual(ok.data["created_by"], self.owner.pk)

        bad = self.client.post(
            self.tasks_url(), {"title": "X", "assignee": self.outsider.pk}, format="json"
        )
        self.assertEqual(bad.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("assignee", bad.data["error"]["details"])

    def test_status_transitions(self):
        task = self.make_task()
        self.login(self.alice)
        url = self.task_url(task)

        res = self.client.patch(url, {"status": "done"}, format="json")  # todo -> done is invalid
        self.assertEqual(res.status_code, 400)
        self.assertIn("status", res.data["error"]["details"])

        for new_status in ["in_progress", "in_review", "done", "in_progress"]:
            res = self.client.patch(url, {"status": new_status}, format="json")
            self.assertEqual(res.status_code, 200, res.data)
            self.assertEqual(res.data["status"], new_status)

    def test_new_task_cannot_start_as_done(self):
        self.login(self.owner)
        res = self.client.post(self.tasks_url(), {"title": "x", "status": "done"}, format="json")
        self.assertEqual(res.status_code, 400)

    def test_filters_sorting_and_search(self):
        today = timezone.localdate()
        t1 = self.make_task(title="Write docs", priority="low", assignee=self.alice,
                            due_date=today + timedelta(days=5))
        t2 = self.make_task(title="Fix login bug", priority="high", assignee=self.bob,
                            due_date=today + timedelta(days=1), status="in_progress")
        t3 = self.make_task(title="Deploy docs site", priority="high", assignee=self.alice,
                            due_date=today + timedelta(days=3))
        self.login(self.owner)

        def titles(query):
            res = self.client.get(self.tasks_url(), query)
            self.assertEqual(res.status_code, 200, res.data)
            return [t["title"] for t in res.data["results"]]

        self.assertEqual(titles({"status": "in_progress"}), ["Fix login bug"])
        self.assertCountEqual(titles({"priority": "high"}), ["Fix login bug", "Deploy docs site"])
        self.assertCountEqual(titles({"assignee": self.alice.pk}), ["Write docs", "Deploy docs site"])
        self.assertEqual(titles({"ordering": "due_date"}), ["Fix login bug", "Deploy docs site", "Write docs"])
        self.assertEqual(titles({"ordering": "-due_date"}), ["Write docs", "Deploy docs site", "Fix login bug"])
        self.assertCountEqual(titles({"search": "docs"}), ["Write docs", "Deploy docs site"])
        self.assertEqual(titles({"priority": "high", "assignee": self.alice.pk}), ["Deploy docs site"])
        self.assertTrue(t1 and t2 and t3)

    def test_pagination(self):
        for i in range(12):
            self.make_task(title=f"T{i}")
        self.login(self.owner)
        res = self.client.get(self.tasks_url())
        self.assertEqual(res.data["count"], 12)
        self.assertEqual(len(res.data["results"]), 10)
        self.assertIsNotNone(res.data["next"])
        res = self.client.get(self.tasks_url(), {"page_size": 5, "page": 3})
        self.assertEqual(len(res.data["results"]), 2)

    def test_soft_delete(self):
        task = self.make_task(created_by=self.alice)
        self.login(self.alice)
        res = self.client.delete(self.task_url(task))
        self.assertEqual(res.status_code, status.HTTP_204_NO_CONTENT)

        self.assertEqual(self.client.get(self.task_url(task)).status_code, 404)
        self.assertEqual(self.client.get(self.tasks_url()).data["count"], 0)

        row = Task.all_objects.get(pk=task.pk)  # still in the database
        self.assertTrue(row.is_deleted)
        self.assertIsNotNone(row.deleted_at)
        self.assertFalse(Task.objects.filter(pk=task.pk).exists())

    def test_only_owner_or_creator_can_delete_task(self):
        task = self.make_task(created_by=self.alice)
        self.login(self.bob)
        self.assertEqual(self.client.delete(self.task_url(task)).status_code, 403)
        self.login(self.owner)
        self.assertEqual(self.client.delete(self.task_url(task)).status_code, 204)

    def test_comments_and_activity_log(self):
        task = self.make_task()
        self.login(self.alice)
        comments_url = reverse("task-comments", kwargs={"project_pk": self.project.pk, "task_pk": task.pk})
        res = self.client.post(comments_url, {"body": "On it!"}, format="json")
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.data["author"]["username"], "alice")
        self.assertEqual(self.client.get(comments_url).data["count"], 1)

        self.client.patch(self.task_url(task), {"status": "in_progress"}, format="json")
        activity_url = reverse("task-activity", kwargs={"project_pk": self.project.pk, "task_pk": task.pk})
        res = self.client.get(activity_url)
        actions = [a["action"] for a in res.data["results"]]
        self.assertIn("status_changed", actions)
        self.assertIn("commented", actions)
        entry = TaskActivity.objects.get(task=task, action="status_changed")
        self.assertEqual((entry.old_value, entry.new_value), ("todo", "in_progress"))


class DashboardTests(BaseTestCase):
    def test_dashboard_counts(self):
        today = timezone.localdate()
        self.make_task(title="a", status="todo", assignee=self.alice, due_date=today - timedelta(days=2))
        self.make_task(title="b", status="in_progress", assignee=self.alice, due_date=today - timedelta(days=1))
        self.make_task(title="c", status="done", assignee=self.bob, due_date=today - timedelta(days=9))
        self.make_task(title="d", status="todo", due_date=today + timedelta(days=4))
        deleted = self.make_task(title="gone", assignee=self.bob)
        deleted.soft_delete()

        self.login(self.alice)
        url = reverse("project-dashboard", kwargs={"pk": self.project.pk})
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200, res.data)

        self.assertEqual(res.data["total_tasks"], 4)
        self.assertEqual(
            res.data["tasks_by_status"], {"todo": 2, "in_progress": 1, "in_review": 0, "done": 1}
        )
        self.assertEqual(res.data["overdue"]["count"], 2)  # the 'done' one is not overdue
        self.assertEqual([t["title"] for t in res.data["overdue"]["tasks"]], ["a", "b"])
        per_member = {m["username"]: m for m in res.data["tasks_per_member"]}
        self.assertEqual(per_member["alice"]["total_tasks"], 2)
        self.assertEqual(per_member["bob"]["total_tasks"], 1)  # soft-deleted not counted
        self.assertEqual(per_member["bob"]["open_tasks"], 0)
        self.assertEqual(per_member["owner"]["total_tasks"], 0)
        self.assertEqual(res.data["unassigned_tasks"], 1)

    def test_dashboard_hidden_from_non_members(self):
        self.login(self.outsider)
        url = reverse("project-dashboard", kwargs={"pk": self.project.pk})
        self.assertEqual(self.client.get(url).status_code, 404)


class AssignmentSignalTests(BaseTestCase):
    def test_email_sent_on_assignment_only_when_assignee_changes(self):
        self.login(self.owner)
        mail.outbox.clear()

        res = self.client.post(self.tasks_url(), {"title": "Ship it", "assignee": self.alice.pk}, format="json")
        self.assertEqual(res.status_code, 201)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["alice@example.com"])
        self.assertIn("Ship it", mail.outbox[0].subject)

        url = reverse("task-detail", kwargs={"project_pk": self.project.pk, "pk": res.data["id"]})
        self.client.patch(url, {"priority": "urgent"}, format="json")  # unrelated change
        self.assertEqual(len(mail.outbox), 1)

        self.client.patch(url, {"assignee": self.bob.pk}, format="json")  # reassigned
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(mail.outbox[1].to, ["bob@example.com"])

        self.client.patch(url, {"assignee": None}, format="json")  # unassigned -> no email
        self.assertEqual(len(mail.outbox), 2)
