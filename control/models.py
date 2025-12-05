from django.db import models

class User(models.Model):
    id = models.UUIDField(primary_key=True)
    email = models.EmailField(unique=True)
    password_hash = models.TextField()
    name_display = models.TextField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    mfa_enabled = models.BooleanField(default=False)
    last_login = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    class Meta:
        db_table = "users"
        managed = False

class Group(models.Model):
    id = models.UUIDField(primary_key=True)
    code = models.TextField(unique=True)
    name = models.TextField()
    status = models.TextField()
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()
    class Meta:
        db_table = "groups"
        managed = False

class Role(models.Model):
    id = models.UUIDField(primary_key=True)
    code = models.TextField(unique=True)
    name = models.TextField()
    class Meta:
        db_table = "roles"
        managed = False

class Permission(models.Model):
    id = models.UUIDField(primary_key=True)
    code = models.TextField(unique=True)
    class Meta:
        db_table = "permissions"
        managed = False

class RolePermission(models.Model):
    role = models.ForeignKey(Role, on_delete=models.CASCADE, db_column="role_id")
    permission = models.ForeignKey(Permission, on_delete=models.CASCADE, db_column="permission_id")
    class Meta:
        db_table = "role_permissions"
        unique_together = ("role", "permission")
        managed = False

class UserGroupMap(models.Model):
    id = models.UUIDField(primary_key=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, db_column="user_id")
    group = models.ForeignKey(Group, on_delete=models.CASCADE, db_column="group_id")
    role  = models.ForeignKey(Role, on_delete=models.RESTRICT, db_column="role_id")
    status = models.TextField()
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()
    class Meta:
        db_table = "user_group_map"
        unique_together = ("user", "group")
        managed = False

class GroupDBConfig(models.Model):
    group      = models.OneToOneField(Group, primary_key=True, on_delete=models.CASCADE, db_column="group_id")
    db_alias   = models.TextField(unique=True)
    db_name    = models.TextField()
    db_host    = models.TextField()
    db_port    = models.IntegerField()
    db_user    = models.TextField()
    db_password= models.TextField()
    # db_extra = models.JSONField(default=dict)  # 선택
    class Meta:
        db_table = "group_db_config"
        managed = False
