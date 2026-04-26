# Evaluation label guide

This guide defines the hand-label contract for `eval/labels.jsonl`. The benchmark is intentionally evidence-first: labels should reflect whether a row is useful for B2B opportunity research, not whether the text is emotionally strong.

## Required decision fields

- `is_pain`: true only for a concrete broken workflow, unmet operational demand, or repeated frustration in a business context.
- `is_monetizable`: true only when a plausible business buyer or budget owner could pay for software to reduce the pain.
- `post_type`: one of `first_person_pain`, `solution_request`, `founder_pitch`, `news_analysis`, `tool_comparison`, `advice_thread`, `vendor_rant`.
- `pain_type`: one of `operational`, `integration`, `reporting`, `billing`, `support`, `compliance`, `security`, `data_quality`, `workflow`, `unknown`.
- `expression_type`: one of `first_person_complaint`, `solution_request`, `wish`, `workaround`, `tool_comparison`, `vendor_rant`, `second_hand_report`, `unknown`.
- `first_handness`: `first_hand`, `second_hand`, `aggregated`, `speculative`, or `unknown`.
- `buyer_authority`: `intern`, `ic`, `engineer`, `manager`, `head_of_ops`, `founder_owner`, `agency_operator`, or `unknown`.
- `intensity_label`, `urgency_label`, `wtp_label`: `none`, `low`, `medium`, or `high`. Use `none` for hard negatives.
- `current_workaround`: current manual workaround or empty string when none is present.
- `incumbent_failure`: why an existing tool/process fails or empty string when absent.
- `evidence_quality`: `no_quote`, `weak_quote`, `exact_quote`, `multi_quote`, or `linked_multi_source`. Checked-in labels also include `evidence_expected` as a backward-compatible derived boolean (`evidence_quality != no_quote`).
- `opportunity_type`: `current_opportunity`, `evergreen_pain`, `research_lead`, `needs_validation`, `not_opportunity`, or `unknown`.
- `is_current_opportunity`: true only when the source timestamp is within the current-opportunity freshness window and the pain is still actionable.
- `hard_negative_type`: `none` for positives; otherwise one of the hard-negative taxonomy values below.
- `reference_now_ts`: fixed timestamp shared by the label file so freshness metrics do not drift.

## Hard-negative taxonomy

Use hard negatives to catch false positives before increasing recall:

- `generic_recommendation`: learning resources, books, templates, podcasts, or generic tool suggestions.
- `generic_opinion`: debate/vibes without a specific broken workflow.
- `b2c_consumer_rant`: real consumer frustration outside the B2B target domain.
- `solved_issue`: historical issue with a provided fix and no ongoing buying signal.
- `founder_pitch`: maker launch, landing-page roast, beta announcement, or self-promotion.
- `news_analysis`: roundup, regulation/policy analysis, benchmark summary, or market commentary.
- `vendor_comparison_no_consequence`: comparison without operational consequence, buyer, or budget signal.
- `low_context_complaint`: frustration with too little detail to verify pain or opportunity.
- `out_of_scope`: anything else outside private B2B opportunity research.

## Positive examples

Label as positive when the row includes all or most of:

1. A concrete workflow or process failure.
2. First-hand operator/buyer language.
3. A workaround or incumbent failure.
4. Exact evidence that can be copied from the source.
5. Freshness for `current_opportunity`, or clear historical usefulness for `evergreen_pain`.

Example: “Head of ops here. We still hand off approvals in Slack and email and it is slowing refunds.”

## Negative examples

Label as negative even if the text sounds painful when it is:

- consumer/B2C pain, e.g. a game crash or food delivery complaint;
- generic learning/resource collection;
- a product launch or founder pitch;
- news or commentary with no first-hand workflow;
- a solved issue posted as documentation;
- a low-context vent with no buyer, sourceable quote, or operational consequence.

## Manual metric placeholders

Optional fields support richer eval metrics:

- `expected_cluster_key`: stable human-readable key for known repeated problems; empty string when not known.
- `evidence_relevance`: `relevant`, `irrelevant`, `not_applicable`, or `unknown`. Use it to judge whether a predicted evidence quote supports the labeled pain.
- `source_link_validity`: `valid`, `invalid`, `not_applicable`, or `unknown`. Use it when checking source/provenance links.
- `feedback_useful`: boolean manual usefulness label for top-N and cost-per-useful-insight metrics.

Fail closed: if a labeler is unsure, use `unknown` only for optional metric placeholders. Required taxonomy fields should be reviewed until they are valid.
