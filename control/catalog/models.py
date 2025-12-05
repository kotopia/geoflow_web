from uuid import uuid4
from django.db import models

class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True

class CategoryNode(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    code = models.TextField(unique=True)
    name = models.TextField()
    level = models.SmallIntegerField()
    ord = models.IntegerField()
    active = models.BooleanField(default=True)
    org_unit_id = models.UUIDField(null=True, blank=True)
    geom_hint = models.TextField(null=True, blank=True)
    class Meta:
        managed = False
        db_table = 'catalog"."category_node'
        ordering = ['level', 'ord', 'name']

class CategoryParent(models.Model):
    parent = models.ForeignKey(CategoryNode, on_delete=models.CASCADE, related_name='children_links', db_column='parent_id')
    child  = models.ForeignKey(CategoryNode, on_delete=models.CASCADE, related_name='parent_links', db_column='child_id', primary_key=True)
    class Meta:
        managed = False
        db_table = 'catalog"."category_parent'
        unique_together = (('parent', 'child'),)
        ordering = ()

class CategoryClosure(models.Model):
    ancestor = models.ForeignKey(CategoryNode, on_delete=models.CASCADE, related_name='descendant_links')
    descendant = models.ForeignKey(CategoryNode, on_delete=models.CASCADE, related_name='ancestor_links')
    depth = models.IntegerField()
    class Meta:
        managed = False
        db_table = 'catalog"."category_closure'
        unique_together = (('ancestor', 'descendant'),)

class CategoryFacet(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    code = models.TextField(unique=True)
    name = models.TextField()
    ord = models.IntegerField()
    active = models.BooleanField(default=True)
    class Meta:
        managed = False
        db_table = 'catalog"."category_facet'
        ordering = ['ord', 'name']

class CategoryFacetOption(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    facet = models.ForeignKey(CategoryFacet, on_delete=models.CASCADE, related_name='options')
    code = models.TextField()
    name = models.TextField()
    ord = models.IntegerField()
    active = models.BooleanField(default=True)
    default_unit = models.TextField(null=True, blank=True)
    geom_hint = models.TextField(null=True, blank=True)
    class Meta:
        managed = False
        db_table = 'catalog"."category_facet_option'
        unique_together = (('facet', 'code'),)
        ordering = ['facet__ord', 'ord', 'name']

class CategoryOptionSet(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    l2 = models.ForeignKey(CategoryNode, on_delete=models.CASCADE, related_name='option_sets')
    facet = models.ForeignKey(CategoryFacet, on_delete=models.CASCADE, related_name='attached_to')
    level_no = models.SmallIntegerField()  # 3 or 4
    ord = models.IntegerField()
    class Meta:
        managed = False
        db_table = 'catalog"."category_option_set'
        unique_together = (('l2', 'level_no', 'facet'),)
        ordering = ['l2__ord', 'level_no']

class CategoryOptionRule(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    l2 = models.ForeignKey(CategoryNode, on_delete=models.CASCADE, related_name='option_rules')
    facet3_opt = models.ForeignKey(CategoryFacetOption, on_delete=models.CASCADE, related_name='as_level3_rules')
    facet4_opt = models.ForeignKey(CategoryFacetOption, on_delete=models.CASCADE, related_name='as_level4_rules')
    active = models.BooleanField(default=True)
    class Meta:
        managed = False
        db_table = 'catalog"."category_option_rule'
        unique_together = (('l2', 'facet3_opt', 'facet4_opt'),)

class CategoryOptionPick(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    l2 = models.ForeignKey(CategoryNode, db_column='l2_id', on_delete=models.DO_NOTHING)
    level_no = models.SmallIntegerField()
    option = models.ForeignKey(CategoryFacetOption, db_column='option_id', on_delete=models.DO_NOTHING)
    ord = models.IntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = False
        db_table = 'catalog"."category_option_pick'
        unique_together = (('l2', 'level_no', 'option'),)
        indexes = [
            models.Index(fields=['l2', 'level_no'], name='cop_l2_level_idx'),
        ]