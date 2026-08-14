from django.core.management.base import BaseCommand, CommandError

from control.services.tenant_provisioning_contract import (
    PROVISIONING_EXECUTION_SEQUENCE,
    TenantProvisioningContractError,
    inspect_tenant_provisioning_plan,
)


class Command(BaseCommand):
    help = "Read-only preflight for a new tenant provisioning plan. Performs no mutations."

    def add_arguments(self, parser):
        parser.add_argument("--group-id", required=True)

    def handle(self, *args, **options):
        try:
            plan = inspect_tenant_provisioning_plan(options["group_id"])
        except TenantProvisioningContractError as exc:
            self.stdout.write(f"tenant_provisioning_plan_blocker={exc.code}")
            self.stdout.write("tenant_provisioning_plan_ready=no")
            raise CommandError("Tenant provisioning plan is not ready") from None

        yes = lambda value: "yes" if bool(value) else "no"
        # Do not print group identifiers, DB names/users/hosts, secret IDs/references,
        # credentials, AWS account data, or ARNs. This command is safe for CI logs.
        self.stdout.write(
            "tenant_provisioning_feature_enabled=" + yes(plan.provisioning_enabled)
        )
        self.stdout.write(
            "tenant_provisioning_provisioner_ready=" + yes(plan.provisioner_ready)
        )
        self.stdout.write(
            "tenant_provisioning_secret_reference_runtime="
            + yes(plan.secret_reference_runtime_required)
        )
        self.stdout.write(
            "tenant_provisioning_runtime_exact_secret_grant_required="
            + yes(plan.runtime_secret_grant_required)
        )
        self.stdout.write(
            "tenant_provisioning_execution_prerequisites_ready="
            + yes(plan.execution_prerequisites_ready)
        )
        self.stdout.write(
            "tenant_provisioning_execution_available=" + yes(plan.execution_available)
        )
        self.stdout.write(
            "tenant_provisioning_publish_config_last="
            + yes(PROVISIONING_EXECUTION_SEQUENCE[-1] == "publish_group_db_config_last")
        )
        self.stdout.write("tenant_provisioning_plan_ready=yes")
