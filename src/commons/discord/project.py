"""The /project workflow: Discord discussion -> lightweight project record.

Discord-free on purpose (same pattern as archive.py) so it can be tested without
a live Discord connection. A project record is deliberately small; v0.1 does not
create a GitHub repository.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from commons.community_repo.git import CommunityRepo
from commons.community_repo.projects import (
    find_project_by_thread,
    find_project_path,
    list_projects,
    plan_project_slug,
    project_relative_path,
    read_project,
    render_project_artifact,
)
from commons.community_repo.schemas import ProjectArtifact, ProjectStatus
from commons.errors import ProjectError
from commons.text import slugify

DEFAULT_STATUS: ProjectStatus = "active"


@dataclass(frozen=True)
class ProjectCreateRequest:
    name: str
    goal: str = ""
    members: list[str] = field(default_factory=list)
    discord_thread_id: int | None = None
    repo: str | None = None


@dataclass(frozen=True)
class ProjectOutcome:
    title: str
    slug: str
    relative_path: str
    status: ProjectStatus
    created: bool
    commit_sha: str | None
    detail: str = ""


class ProjectService:
    """Idempotent project-record writer."""

    def __init__(self, repo: CommunityRepo) -> None:
        self.repo = repo

    @property
    def data_root(self) -> Path:
        return self.repo.path / "data"

    def create(self, request: ProjectCreateRequest) -> ProjectOutcome:
        name = request.name.strip()
        if not name:
            raise ProjectError("project name must not be empty")

        if request.discord_thread_id is not None:
            linked = find_project_by_thread(self.data_root, request.discord_thread_id)
            if linked is not None:
                project = read_project(linked)
                return self._outcome(
                    project,
                    linked,
                    created=False,
                    detail="this Discord thread is already linked to a project",
                )

        existing = find_project_path(self.data_root, slugify(name))
        if existing is not None:
            project = read_project(existing)
            return self._outcome(
                project,
                existing,
                created=False,
                detail=(
                    "a project with this name already exists; returning it instead of overwriting"
                ),
            )

        project = ProjectArtifact(
            title=name,
            status=DEFAULT_STATUS,
            members=list(request.members),
            discord_thread_id=request.discord_thread_id,
            repo=request.repo,
            goal=request.goal.strip(),
        )
        slug = plan_project_slug(self.data_root, name)
        relative_path = project_relative_path(slug)
        result = self.repo.write_artifact(
            relative_path,
            render_project_artifact(project),
            commit_message=f"project: create {slug} project",
        )
        return ProjectOutcome(
            title=project.title,
            slug=slug,
            relative_path=relative_path,
            status=project.status,
            created=True,
            commit_sha=result.commit_sha,
            detail=result.detail,
        )

    def set_status(self, slug: str, status: ProjectStatus) -> ProjectOutcome:
        """Change status. v0.1 exposes this through tests and manual Git edits."""

        path = find_project_path(self.data_root, slug)
        if path is None:
            raise ProjectError(f"no project record for {slug!r}")
        project = read_project(path)
        updated = project.model_copy(update={"status": status})
        result = self.repo.write_artifact(
            project_relative_path(slug),
            render_project_artifact(updated),
            commit_message=f"project: set {slug} status to {status}",
        )
        return self._outcome(
            updated,
            path,
            created=False,
            detail=f"status updated to {status}",
            commit_sha=result.commit_sha,
        )

    def list(self) -> list[ProjectArtifact]:
        return list_projects(self.data_root)

    def _outcome(
        self,
        project: ProjectArtifact,
        path: Path,
        *,
        created: bool,
        detail: str,
        commit_sha: str | None = None,
    ) -> ProjectOutcome:
        return ProjectOutcome(
            title=project.title,
            slug=path.stem,
            relative_path=path.relative_to(self.repo.path).as_posix(),
            status=project.status,
            created=created,
            commit_sha=commit_sha,
            detail=detail,
        )
