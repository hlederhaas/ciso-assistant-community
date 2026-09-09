<script lang="ts">
	import { m } from '$paraglide/messages';
	import { safeTranslate } from '$lib/utils/i18n';
	import MarkdownRenderer from '$lib/components/MarkdownRenderer.svelte';
	let { snapshot }: { snapshot: any } = $props();
	const content = $derived(snapshot?.content);
	const matrix = $derived.by(() => {
		try {
			return typeof content?.matrix === 'string' ? JSON.parse(content.matrix) : content?.matrix;
		} catch {
			return null;
		}
	});
	function rating(kind: string, index: number) {
		return matrix?.[kind]?.[index]?.name ?? (index < 0 ? '—' : String(index));
	}
</script>

{#if content}
	<div class="space-y-3 text-sm mt-3">
		<h3 class="font-semibold">
			{m.riskApprovalSnapshot()}: {content.scenario.ref_id}
			{content.scenario.name}
		</h3>
		<MarkdownRenderer content={content.scenario.description ?? ''} />
		<MarkdownRenderer content={content.scenario.justification ?? ''} />
		<dl class="grid grid-cols-2 gap-2">
			<dt>{m.currentProba()}</dt>
			<dd>{rating('probability', content.assessment.current_proba)}</dd>
			<dt>{m.currentImpact()}</dt>
			<dd>{rating('impact', content.assessment.current_impact)}</dd>
			<dt>{m.currentRisk()}</dt>
			<dd>{rating('risk', content.assessment.current_level)}</dd>
			{#if content.treatment}
				<dt>{m.treatment()}</dt>
				<dd>{safeTranslate(content.treatment.treatment)}</dd>
				<dt>{m.residualProba()}</dt>
				<dd>{rating('probability', content.treatment.residual_proba)}</dd>
				<dt>{m.residualImpact()}</dt>
				<dd>{rating('impact', content.treatment.residual_impact)}</dd>
				<dt>{m.residualRisk()}</dt>
				<dd>{rating('risk', content.treatment.residual_level)}</dd>
				{#if content.risk_governance?.risk_tolerance >= 0}
					<dt>{m.riskTolerance()}</dt>
					<dd>{rating('risk', content.risk_governance.risk_tolerance)}</dd>
				{/if}
			{/if}
		</dl>
		{#if content.assets?.length}<p>
				{m.assets()}: {content.assets.map((asset: any) => asset.name).join(', ')}
			</p>{/if}
		{#each [{ title: m.existingControls(), controls: content.existing_controls }, { title: m.treatmentPlan(), controls: content.planned_controls }] as group}
			{#if group.controls?.length}
				<h4 class="font-semibold">{group.title}</h4>
				{#each group.controls as control}
					<div class="border border-surface-200-800 rounded p-3 space-y-1">
						<p class="font-medium">{control.name}</p>
						<MarkdownRenderer content={control.description ?? ''} />
						<p>
							{m.owner()}: {control.owner_names?.join(', ') || '—'} · {m.eta()}: {control.eta ??
								'—'}
						</p>
						{#if control.status}<p>{m.status()}: {safeTranslate(control.status)}</p>{/if}
					</div>
				{/each}
			{/if}
		{/each}
	</div>
{/if}
