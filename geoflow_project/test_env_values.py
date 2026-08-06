from unittest import TestCase

from geoflow_project.env_values import (
    get_optional_env_int,
    get_optional_env_text,
    get_optional_env_text_mapping,
)


class OptionalEnvironmentValueTests(TestCase):
    def test_absent_or_blank_optional_values_do_not_force_feature_enablement(self):
        self.assertIsNone(get_optional_env_text({}, "TEXT"))
        self.assertIsNone(get_optional_env_text({"TEXT": "  "}, "TEXT"))
        self.assertIsNone(
            get_optional_env_int(
                {},
                "COUNT",
                minimum=1,
                maximum=10,
            )
        )
        self.assertEqual(get_optional_env_text_mapping({}, "KEYS"), {})

    def test_valid_text_integer_and_mapping_are_normalized(self):
        environ = {
            "TEXT": " current ",
            "COUNT": "7200",
            "KEYS": '{"current":" encoded-value ","previous":"old-value"}',
        }

        self.assertEqual(get_optional_env_text(environ, "TEXT"), "current")
        self.assertEqual(
            get_optional_env_int(
                environ,
                "COUNT",
                minimum=60,
                maximum=604800,
            ),
            7200,
        )
        self.assertEqual(
            get_optional_env_text_mapping(environ, "KEYS"),
            {
                "current": "encoded-value",
                "previous": "old-value",
            },
        )

    def test_invalid_integer_error_exposes_name_not_value(self):
        secret_like_value = "not-an-integer-secret"

        with self.assertRaises(RuntimeError) as raised:
            get_optional_env_int(
                {"COUNT": secret_like_value},
                "COUNT",
                minimum=1,
                maximum=10,
            )

        self.assertIn("COUNT", str(raised.exception))
        self.assertNotIn(secret_like_value, str(raised.exception))

    def test_out_of_range_integer_is_rejected_without_value_echo(self):
        with self.assertRaises(RuntimeError) as raised:
            get_optional_env_int(
                {"COUNT": "999999"},
                "COUNT",
                minimum=1,
                maximum=10,
            )

        self.assertNotIn("999999", str(raised.exception))

    def test_invalid_json_error_exposes_name_not_secret_payload(self):
        secret_like_value = "{broken-secret-payload"

        with self.assertRaises(RuntimeError) as raised:
            get_optional_env_text_mapping(
                {"KEYS": secret_like_value},
                "KEYS",
            )

        self.assertIn("KEYS", str(raised.exception))
        self.assertNotIn(secret_like_value, str(raised.exception))

    def test_mapping_requires_nonempty_string_keys_and_values(self):
        invalid_values = (
            "[]",
            "{}",
            '{"":"value"}',
            '{"current":""}',
            '{"current":123}',
        )
        for value in invalid_values:
            with self.subTest(value=value):
                with self.assertRaises(RuntimeError):
                    get_optional_env_text_mapping(
                        {"KEYS": value},
                        "KEYS",
                    )
