"""Scenario-level decisions using the validation flow event trail.

Snapshots are semantic: changing a label unrelated to the decision does not
invalidate it. Plans and existing controls are captured, not merely linked.
No decision changes a scenario's treatment option or locks its whole study.
"""

import json

from django.contrib.auth.models import Permission
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.utils import timezone
from global_settings.utils import ff_is_enabled
from iam.models import RoleAssignment, User
from rest_framework.exceptions import PermissionDenied, ValidationError

from core.models import Actor, FlowEvent, RiskScenario, ValidationFlow


def risk_approvals_enabled():
    """Return whether both flags required by risk approvals are enabled."""
    return ff_is_enabled("validation_flows") and ff_is_enabled("risk_owner_approvals")


def _require_risk_approvals_enabled():
    """Reject risk-approval writes while the optional workflow is disabled."""
    if not risk_approvals_enabled():
        raise PermissionDenied("riskApprovalFeatureDisabled")


def owner_can_approve(scenario, user):
    """Check named ownership, object visibility and approval permission."""
    if not user or not user.is_active:
        return False
    return (
        scenario.owner.filter(
            pk__in=[a.pk for a in Actor.get_all_for_user(user)]
        ).exists()
        and RoleAssignment.is_object_readable(user, RiskScenario, scenario.pk)
        and RoleAssignment.is_access_allowed(
            user,
            Permission.objects.get(codename="change_validationflow"),
            scenario.folder,
        )
    )


def approval_candidates(scenario):
    """Return active named users allowed to approve the scenario."""
    # Resolve teams and entity representatives through the application's actor
    # rules. The actual decision still belongs to one named, authorised user.
    return [
        {"id": str(user.pk), "email": user.email, "name": str(user)}
        for user in User.objects.filter(is_active=True).order_by("email")
        if owner_can_approve(scenario, user)
    ]


def _values(obj, fields):
    """Copy decision-relevant model fields into a serialisable mapping."""
    return {field: getattr(obj, field) for field in fields}


def _controls(manager, planned=False):
    """Capture control content while ignoring progress on planned controls."""
    return [
        {
            **_values(
                control,
                ["name", "description", "eta", "start_date"]
                + ([] if planned else ["status"]),
            ),
            "id": str(control.pk),
            "owners": sorted(
                str(pk) for pk in control.owner.values_list("pk", flat=True)
            ),
            "owner_names": [str(owner) for owner in control.owner.order_by("pk")],
        }
        for control in manager.order_by("pk")
    ]


def snapshot(scenario, stage):
    """Build the semantic scenario state covered by an approval request."""
    data = {
        "scenario": {
            "id": str(scenario.pk),
            **_values(scenario, ["ref_id", "name", "description", "justification"]),
        },
        "folder": str(scenario.folder_id),
        "study": str(scenario.risk_assessment_id),
        "matrix": scenario.risk_assessment.risk_matrix.json_definition,
        "owners": sorted(str(pk) for pk in scenario.owner.values_list("pk", flat=True)),
        "assets": [
            {"id": str(asset.pk), "name": asset.name, "description": asset.description}
            for asset in scenario.assets.order_by("pk")
        ],
        "threats": sorted(
            str(pk) for pk in scenario.threats.values_list("pk", flat=True)
        ),
        "vulnerabilities": sorted(
            str(pk) for pk in scenario.vulnerabilities.values_list("pk", flat=True)
        ),
        "assessment": _values(
            scenario,
            [
                "inherent_proba",
                "inherent_impact",
                "inherent_level",
                "current_proba",
                "current_impact",
                "current_level",
                "strength_of_knowledge",
                "existing_controls",
            ],
        ),
        "existing_controls": _controls(scenario.existing_applied_controls),
    }
    if stage == "treatment":
        data["treatment"] = _values(
            scenario,
            ["treatment", "residual_proba", "residual_impact", "residual_level"],
        )
        data["planned_controls"] = _controls(scenario.applied_controls, planned=True)
    return json.loads(json.dumps(data, cls=DjangoJSONEncoder))


def is_current(flow):
    """Check that content, authority and prerequisite approval still match."""
    if not flow.risk_scenario_id or not flow.risk_snapshot:
        return False
    # Callers may retain a flow instance while its scenario is edited elsewhere.
    # Compare against persisted content, never the FK's stale instance cache.
    scenario = RiskScenario.objects.select_related("risk_assessment__risk_matrix").get(
        pk=flow.risk_scenario_id
    )
    if not owner_can_approve(scenario, flow.approver):
        return False
    if flow.risk_snapshot.get("content") != snapshot(
        scenario, flow.risk_approval_stage
    ):
        return False
    if flow.risk_approval_stage == "treatment":
        rating = ValidationFlow.objects.filter(
            pk=flow.risk_snapshot.get("assessment_approval"),
            risk_scenario=scenario,
            risk_approval_stage="assessment",
            status="accepted",
        ).first()
        return bool(rating and is_current(rating))
    return True


def capture(scenario, stage, approver):
    """Validate a request and capture its immutable decision state."""
    if not owner_can_approve(scenario, approver):
        raise ValidationError({"approver": "riskApprovalOwnerRequired"})
    if scenario.current_proba < 0 or scenario.current_impact < 0:
        raise ValidationError("riskApprovalRatingRequired")
    data = {"content": snapshot(scenario, stage)}
    if stage == "treatment":
        if (
            scenario.treatment in ("open", "cancelled")
            or min(scenario.residual_proba, scenario.residual_impact) < 0
        ):
            raise ValidationError("riskApprovalTreatmentRequired")
        rating = next(
            (
                flow
                for flow in scenario.risk_approvals.filter(
                    risk_approval_stage="assessment", status="accepted"
                ).order_by("-created_at")
                if is_current(flow)
            ),
            None,
        )
        if rating is None:
            raise ValidationError("riskApprovalAssessmentFirst")
        data["assessment_approval"] = str(rating.pk)
    return data


@transaction.atomic
def create_approval(data, user):
    """Create a locked risk-approval request and its initial history event."""
    _require_risk_approvals_enabled()
    data = data.copy()
    scenario = RiskScenario.objects.select_for_update().get(pk=data["risk_scenario"].pk)
    if not RoleAssignment.is_object_readable(user, RiskScenario, scenario.pk):
        raise PermissionDenied()
    if data["folder"].pk != scenario.folder_id:
        raise ValidationError({"folder": "riskApprovalSameDomain"})
    stage = data.get("risk_approval_stage")
    if stage not in ValidationFlow.RiskApprovalStage.values:
        raise ValidationError({"risk_approval_stage": "riskApprovalStageRequired"})
    # A risk decision must not silently lock another bundled object.
    for field in ValidationFlow._meta.many_to_many:
        if data.pop(field.name, None):
            raise ValidationError("riskApprovalSingleScenario")
    data.pop("confirm_residual_risk", None)
    notes = data.pop("event_notes", None) or data.get("request_notes")
    data["risk_snapshot"] = capture(scenario, stage, data.get("approver"))
    data["requester"] = user
    flow = ValidationFlow.objects.create(**data)
    FlowEvent.objects.create(
        validation_flow=flow,
        folder=flow.folder,
        event_actor=user,
        event_type=flow.status,
        event_notes=notes,
        risk_snapshot=flow.risk_snapshot,
    )
    _notify_after_commit(flow, created=True)
    return flow


@transaction.atomic
def update_approval(flow, data, user):
    """Apply one authorised state transition to a locked approval request."""
    _require_risk_approvals_enabled()
    flow = ValidationFlow.objects.select_for_update().get(pk=flow.pk)
    allowed = {"status", "event_notes", "confirm_residual_risk"}
    if set(data) - allowed or "status" not in data:
        raise ValidationError("riskApprovalImmutable")
    old, new = flow.status, data["status"]
    transitions = {
        "submitted": {"accepted", "rejected", "change_requested", "dropped"},
        "accepted": {"revoked"},
        "change_requested": {"submitted", "dropped"},
    }
    if new not in transitions.get(old, set()):
        raise ValidationError("riskApprovalInvalidTransition")
    authorised = user.pk == flow.approver_id
    if old == "change_requested":
        authorised = user.pk == flow.requester_id
    elif old == "submitted" and new == "dropped":
        authorised = user.pk in (flow.requester_id, flow.approver_id)
    if not authorised:
        raise PermissionDenied("validationOnlyApproverCanModify")
    scenario = RiskScenario.objects.select_for_update().get(pk=flow.risk_scenario_id)
    flow.risk_scenario = scenario
    residual_accepted = False
    if new == "accepted":
        if flow.validation_deadline and flow.validation_deadline < timezone.localdate():
            raise ValidationError("riskApprovalDeadlinePassed")
        if not is_current(flow):
            raise ValidationError("riskApprovalStale")
        residual_accepted = flow.risk_approval_stage == "treatment"
        if residual_accepted and data.get("confirm_residual_risk") is not True:
            raise ValidationError("riskApprovalResidualConfirmation")
    elif new == "submitted":
        flow.risk_snapshot = capture(scenario, flow.risk_approval_stage, flow.approver)
    flow.status = new
    flow.save(update_fields=["status", "risk_snapshot", "updated_at"])
    FlowEvent.objects.create(
        validation_flow=flow,
        folder=flow.folder,
        event_actor=user,
        event_type=new,
        event_notes=data.get("event_notes"),
        risk_snapshot=flow.risk_snapshot,
        residual_risk_accepted=residual_accepted,
    )
    _notify_after_commit(flow, actor=user)
    return flow


def _notify_after_commit(flow, created=False, actor=None):
    """Send notifications after commit without affecting saved decisions."""

    def send():
        import structlog

        from core.tasks import (
            send_validation_flow_created_notification,
            send_validation_flow_updated_notification,
        )

        try:
            if created:
                send_validation_flow_created_notification(flow)
            else:
                recipient = (
                    flow.requester if actor.pk == flow.approver_id else flow.approver
                )
                if recipient and recipient.email:
                    send_validation_flow_updated_notification(
                        flow.pk,
                        recipient.email,
                        flow.get_status_display(),
                        str(actor),
                        flow.last_event_notes,
                    )
        except Exception:
            structlog.get_logger(__name__).exception(
                "Risk approval notification failed"
            )

    transaction.on_commit(send)
