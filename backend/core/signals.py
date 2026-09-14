from django.db.models.signals import m2m_changed, pre_delete
from django.dispatch import receiver
from django.utils import timezone
from structlog import get_logger

from core.models import EvidenceRevision, RiskScenario

logger = get_logger(__name__)


@receiver(pre_delete, sender=EvidenceRevision)
def _delete_evidence_revision_attachment(sender, instance: EvidenceRevision, **kwargs):
    if instance.attachment and instance.attachment.name:
        try:
            instance.attachment.delete(save=False)
        except Exception as e:
            logger.warning(
                "Failed to delete evidence revision attachment",
                revision_id=instance.pk,
                evidence_id=instance.evidence_id,
                error=str(e),
            )


RISK_SCENARIO_DECISION_RELATIONS = {
    RiskScenario.owner.through: "risk_scenarios",
    RiskScenario.assets.through: "risk_scenarios",
    RiskScenario.threats.through: "risk_scenarios",
    RiskScenario.vulnerabilities.through: "risk_scenarios",
    RiskScenario.applied_controls.through: "risk_scenarios",
    RiskScenario.existing_applied_controls.through: "risk_scenarios_e",
    RiskScenario.incidents.through: "risk_scenarios",
    RiskScenario.qualifications.through: "risk_scenarios_qualifications",
    RiskScenario.security_exceptions.through: "risk_scenarios",
    RiskScenario.antecedent_scenarios.through: "consequent_scenarios",
}


def _touch_risk_scenario(sender, instance, action, reverse, pk_set, **kwargs):
    """Keep updated_at meaningful when decision-relevant M2M content changes."""
    if action == "pre_clear" and reverse:
        accessor = RISK_SCENARIO_DECISION_RELATIONS[sender]
        getattr(instance, accessor).update(updated_at=timezone.now())
        return
    if action not in {"post_add", "post_remove", "post_clear"}:
        return
    now = timezone.now()
    if not reverse:
        RiskScenario.objects.filter(pk=instance.pk).update(updated_at=now)
    elif pk_set:
        RiskScenario.objects.filter(pk__in=pk_set).update(updated_at=now)


for relation in RISK_SCENARIO_DECISION_RELATIONS:
    m2m_changed.connect(
        _touch_risk_scenario,
        sender=relation,
        dispatch_uid=f"touch-risk-scenario-{relation._meta.label_lower}",
    )
