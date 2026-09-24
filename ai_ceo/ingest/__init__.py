"""Turn a GitHub repository or a VPS into a ProductDossier."""
from .github import ingest_github, is_github_url
from .vps import ingest_vps, is_ssh_target

__all__ = ["ingest_github", "is_github_url", "ingest_vps", "is_ssh_target"]
