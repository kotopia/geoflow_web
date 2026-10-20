"""Public contract of independent observations and assets."""
from django.test import SimpleTestCase
from django.urls import Resolver404, resolve

from .qgis_manifest import build_qgis_manifest


class IndependentSurveyContractTests(SimpleTestCase):
    def test_retired_routes_have_no_compatibility_view(self):
        project = '11111111-1111-4111-8111-111111111401'
        for suffix in ('survey-links/', 'survey-link-changesets/',
                       'qfield/survey-links/', 'qfield/survey-link-changesets/',
                       'survey-reapply/', 'survey-reapply-preview/'):
            with self.subTest(suffix=suffix), self.assertRaises(Resolver404):
                resolve(f'/gis/projects/{project}/api/{suffix}')

    def test_manifest_exposes_only_existing_survey_resources(self):
        manifest = build_qgis_manifest(project={'id':'p'},plan={},can_write=True,
                                       package_url='/package',package_layers=[],
                                       changeset_supported=True,changeset_url='/changes',delta_url='/delta')
        transport = manifest['transport']
        self.assertTrue(transport['survey_sources_url'])
        self.assertTrue(transport['survey_points_url'])
        self.assertFalse(any('survey_link' in k or 'reapply' in k for k in transport))
