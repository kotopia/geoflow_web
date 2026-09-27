# 제목: ui/__init__.py
# 기능: ui 패키지; import 시 별도 서비스나 플러그인을 시작하지 않음

# Designer forms resolve ``:/geoflow/feather`` after this side-effect import.
# Keep pure-Python helpers (for example the image normalizer) importable in the
# repository test environment where the QGIS Python bindings are unavailable.
try:
    from ..resources import feather_rc  # noqa: F401
except ModuleNotFoundError as exc:
    if exc.name != "qgis":
        raise
