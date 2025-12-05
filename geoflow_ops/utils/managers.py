from django.db import models
from .querysets import ProjectQuerySet

class ProjectManager(models.Manager.from_queryset(ProjectQuerySet)):
    """ProjectManagement 전용 매니저"""
    pass
