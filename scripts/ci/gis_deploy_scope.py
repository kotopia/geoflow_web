"""Keep plugin-only pushes out of the server/DB deployment job."""
import argparse
import re
import subprocess

PLUGIN_ONLY_PATHS = frozenset({
    "docs/operations/qgis-plugin-stable-release.json",
    "docs/architecture/gis-direction-editing.md",
    "docs/development/qgis-connector-mvp.md",
    ".github/workflows/qgis-plugin-stable-repository-publish.yml",
    ".github/workflows/gis-definition-code-deploy.yml",
    "geoflow_ops/test_qgis_plugin_repository_publish_contract.py",
    "scripts/ci/gis_deploy_scope.py",
})


def requires_server_deploy(paths):
    return any(not path.startswith("integrations/qgis/geoflow_connector/")
               and path not in PLUGIN_ONLY_PATHS for path in paths)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--event", required=True)
    parser.add_argument("--before", default="")
    parser.add_argument("--after", required=True)
    args = parser.parse_args()
    if args.event == "workflow_dispatch":
        required = True
    elif args.event == "push":
        for revision in (args.before, args.after):
            if not re.fullmatch(r"[0-9a-f]{40}", revision) or revision == "0" * 40:
                raise SystemExit("Cannot classify release revisions; deployment remains blocked")
        paths = subprocess.check_output([
            "git", "diff", "--name-only", "--no-renames", "-z", args.before, args.after
        ]).decode("utf-8").split("\0")
        required = requires_server_deploy(path for path in paths if path)
    else:
        raise SystemExit("Unsupported deployment event")
    print("server_deploy=" + str(required).lower())


if __name__ == "__main__":
    main()
