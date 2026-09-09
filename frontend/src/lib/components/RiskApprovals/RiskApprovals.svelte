<script lang="ts">
	import { enhance } from '$app/forms';
	import { m } from '$paraglide/messages';
	import { safeTranslate } from '$lib/utils/i18n';
	import Anchor from '$lib/components/Anchor/Anchor.svelte';
	let {
		flows,
		approvers,
		canRequest,
		errorMessage = ''
	}: {
		flows: any[];
		approvers: { id: string; email: string; name: string }[];
		canRequest: boolean;
		errorMessage?: string;
	} = $props();
	let stage = $state('assessment');
	let pending = $state(false);
	const ratingApproved = $derived(
		flows.some(
			(flow) =>
				flow.risk_approval_stage === 'assessment' &&
				flow.status === 'accepted' &&
				flow.risk_approval_current
		)
	);
</script>

<section class="card p-4 space-y-4 bg-surface-50-950" data-testid="risk-approvals">
	<h2 class="text-lg font-semibold">{m.riskApprovals()}</h2>
	<p class="text-sm">{m.riskApprovalHelp()}</p>
	{#each flows as flow (flow.id)}
		<div class="flex flex-wrap items-center gap-3 border-b border-surface-200-800 pb-2">
			<Anchor href="/validation-flows/{flow.id}" class="anchor">{flow.ref_id}</Anchor>
			<span
				>{flow.risk_approval_stage === 'assessment'
					? m.riskApprovalAssessment()
					: m.riskApprovalTreatment()}</span
			>
			<span class="badge">{safeTranslate(flow.status)}</span>
			{#if ['accepted', 'submitted'].includes(flow.status) && !flow.risk_approval_current}
				<span class="badge preset-tonal-warning">{m.riskApprovalOutdated()}</span>
			{/if}
			<span class="text-sm">{flow.approver?.email}</span>
		</div>
	{/each}
	{#if canRequest}
		{#if approvers.length === 0}
			<p class="text-sm preset-tonal-warning p-3">{m.riskApprovalNoOwner()}</p>
		{:else}
			<form
				method="POST"
				action="?/requestApproval"
				class="space-y-3"
				use:enhance={() => {
					pending = true;
					return async ({ update }) => {
						try {
							await update({ reset: false });
						} finally {
							pending = false;
						}
					};
				}}
			>
				<div class="grid gap-3 md:grid-cols-3">
					<label class="label"
						><span>{m.riskApprovalStage()}</span>
						<select name="stage" bind:value={stage} class="select">
							<option value="assessment">{m.riskApprovalAssessment()}</option>
							<option value="treatment" disabled={!ratingApproved}
								>{m.riskApprovalTreatment()}</option
							>
						</select>
					</label>
					<label class="label"
						><span>{m.approver()}</span>
						<select name="approver" class="select" required>
							{#each approvers as approver}<option value={approver.id}
									>{approver.name || approver.email}</option
								>{/each}
						</select>
					</label>
					<label class="label"
						><span>{m.validationDeadline()}</span><input
							class="input"
							type="date"
							name="deadline"
						/></label
					>
				</div>
				{#if !ratingApproved}<p class="text-sm">{m.riskApprovalAssessmentFirst()}</p>{/if}
				<label class="label"
					><span>{m.requestNotes()}</span><textarea
						class="textarea"
						name="notes"
						rows="2"
						maxlength="10000"
					></textarea></label
				>
				{#if errorMessage}<p role="alert" class="preset-tonal-error p-3">{errorMessage}</p>{/if}
				<button class="btn preset-filled-primary-500" disabled={pending} type="submit"
					>{m.riskApprovalRequest()}</button
				>
			</form>
		{/if}
	{/if}
</section>
