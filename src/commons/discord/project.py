"""The /project workflow: Discord discussion -> lightweight project record.

Discord-free on purpose (same pattern as archive.py) so it can be tested without
a live Discord connection. A project record is deliberately small; v0.1 does not
create a GitHub repository. Thread/name idempotency and slug allocation happen
inside the repository lock (review R02).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from commons.community_repo.git import ArtifactPlan, CommunityRepo
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


def _relative_to(repo_path: Path, path: Path) -> str:
    return path.relative_to(repo_path).as_posix()


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

        new_project = ProjectArtifact(
            title=name,
            status=DEFAULT_STATUS,
            members=list(request.members),
            discord_thread_id=request.discord_thread_id,
            repo=request.repo,
            goal=request.goal.strip(),
        )
        content = render_project_artifact(new_project)
        found: dict[str, ProjectArtifact] = {}

        def prepare(root: Path) -> ArtifactPlan:
            data_root = root / "data"
            if request.discord_thread_id is not None:
                linked = find_project_by_thread(data_root, request.discord_thread_id)
                if linked is not None:
                    found["project"] = read_project(linked)
                    return ArtifactPlan(
                        relative_path=_relative_to(root, linked),
                        content=None,
                        detail="this Discord thread is already linked to a project",
                    )
            existing = find_project_path(data_root, slugify(name))
            if existing is not None:
                found["project"] = read_project(existing)
                return ArtifactPlan(
                    relative_path=_relative_to(root, existing),
                    content=None,
                    detail=(
                        "a project with this name already exists; "
                        "returning it instead of overwriting"
                    ),
                )
            slug = plan_project_slug(data_root, name)
            return ArtifactPlan(relative_path=project_relative_path(slug), content=content)

        locked = self.repo.write_artifact_locked(
            commit_message=f"project: create {slugify(name)} project",
            prepare=prepare,
        )
        plan = locked.plan
        if plan is None:
            raise ProjectError("project creation produced no plan")

        created = plan.content is not None
        project = found.get("project", new_project)
        detail = locked.git.detail
        if not created:
            detail = plan.detail
            if locked.git.pushed:
                detail = f"{plan.detail} ({locked.git.detail})"
        return ProjectOutcome(
            title=project.title,
            slug=Path(plan.relative_path).stem,
            relative_path=plan.relative_path,
            status=project.status,
            created=created,
            commit_sha=locked.git.commit_sha,
            detail=detail,
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
        return ProjectOutcome(
            title=updated.title,
            slug=slug,
            relative_path=project_relative_path(slug),
            status=updated.status,
            created=False,
            commit_sha=result.commit_sha,
            detail=f"status updated to {status}",
        )

    def list(self) -> list[ProjectArtifact]:
        return list_projects(self.data_root)
