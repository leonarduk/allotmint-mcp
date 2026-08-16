# Responsible AI and governance: `allotmint_research`

**Document owner:** AllotMint maintainers  
**Applies to:** the optional `allotmint_research` tool and its research-agent service  
**Review trigger:** material changes to the model, tools, data sources, intended use, or law; otherwise at least annually  
**Last reviewed:** 16 August 2026

> This document is a product-governance aid, not legal advice. A deploying
> organisation remains responsible for assessing its particular use, users,
> jurisdiction, data, and model provider with legal and compliance advisers.

## Executive summary

`allotmint_research` is an optional, read-only research assistant. It combines
retrieved documents with live results from four existing AllotMint tools and
uses a language model to produce a natural-language answer with citations. It
can help a person investigate portfolio, instrument, and market information; it
does not trade, change a portfolio, or make an automated decision.

For the intended use described below, the maintainers consider the tool a
**decision-support, limited-risk application**, not an EU AI Act prohibited
practice or Annex III high-risk system. That is an initial product
classification, not a certification. Classification depends on use: an
organisation must reassess it before using the output to make or materially
influence decisions about a person, including creditworthiness, access to
essential services, employment, insurance, or another regulated activity.

The tool can be wrong, incomplete, stale, or manipulated. Citations demonstrate
which sources were available to a run; they do not prove that every statement
is correct. Existing deterministic guardrails flag some suspicious or weakly
grounded results for review, but the flag is advisory and does not suppress the
answer. A qualified human must verify important outputs against authoritative
sources.

## Intended use and limitations

### Appropriate uses

- exploratory research and summarisation of AllotMint portfolio, instrument,
  and market information;
- locating potentially relevant facts and sources for a human analyst;
- drafting a research starting point whose claims, calculations, and citations
  will be independently checked; and
- demonstrations, testing, and evaluation with non-sensitive or appropriately
  authorised data.

### Do not rely on it for

- investment, legal, tax, accounting, credit, insurance, or other professional
  advice;
- executing trades, changing holdings, or any other write operation;
- autonomous decisions or recommendations that affect a person's rights,
  eligibility, employment, credit, insurance, or access to services;
- definitive current prices, news, regulatory status, or portfolio values
  without checking the underlying authoritative source and its timestamp;
- emergency, safety-critical, or otherwise high-consequence decisions;
- handling secrets, credentials, special-category personal data, or information
  the operator is not authorised to send to every configured service; or
- claims that a cited source necessarily supports the generated interpretation.

### Known failure modes

Language models can fabricate facts or citations, misread retrieved material,
perform arithmetic incorrectly, omit relevant context, reproduce bias in source
material, follow malicious instructions in user or retrieved content, and vary
with model or configuration changes. Retrieval can return irrelevant, stale, or
owner-inappropriate material if data was ingested or labelled incorrectly.
External AllotMint tools and upstream data can also be unavailable or wrong.

The current controls reduce, but do not eliminate, these risks:

- only four configured, read-only MCP tools are callable; future tools are not
  automatically trusted, and the agent cannot call itself;
- a configurable tool-call limit bounds the agent loop;
- citations are assembled from retrieved documents and recorded tool calls,
  rather than accepted from the model as evidence;
- an answer with neither retrieved context nor tool calls is marked ungrounded
  and rejected by the Java-facing tool; and
- deterministic review checks flag recognised prompt-injection phrases,
  requests to invent information, suspicious tool arguments, missing or invalid
  citation markers, and likely missing tool calls.

The pattern checks are deliberately narrow. They are not a general prompt-
injection detector, do not establish truth, do not inspect source documents for
indirect prompt injection, and can produce false positives and false negatives.
`needs_review=true` is a warning to the caller, not a technical approval gate.

## Risk classification and required reassessment

| Question | Intended-use assessment | Reassessment trigger |
|---|---|---|
| Does it make decisions or take action? | No. It returns text and has read-only tool access. | Adding write tools, automatic execution, ranking, or decision logic. |
| Is it an EU AI Act prohibited practice? | None is intended. | Use involving manipulation, exploitation, social scoring, prohibited biometric practices, or another Article 5 category. Stop and obtain legal review. |
| Is it an Annex III high-risk use? | Not for general investment research as documented here. | Use for employment, education, creditworthiness, life/health insurance risk assessment or pricing, essential services, law enforcement, migration, justice, or another Annex III purpose. |
| Does it interact directly with people? | It may do so through an MCP client. | The deployer must make the AI nature clear where it is not already obvious and assess Article 50 transparency duties. |
| Is AllotMint the provider of a general-purpose AI model? | No model is developed here; the operator configures a local or third-party model. | Fine-tuning, branding, or placing a model on the EU market may change roles and obligations; review model-provider terms and documentation. |
| Is personal or confidential data processed? | Portfolio requests can contain owner-linked financial information. | Before production use, document lawful access, minimisation, retention, recipients, international transfers, and incident handling under applicable privacy/security rules. |

The [EU AI Act](https://eur-lex.europa.eu/eli/reg/2024/1689/oj) is
risk- and role-based. Whether an organisation is a provider, deployer,
importer, distributor, or product manufacturer—and whether a system is
high-risk—depends on how it is placed on the market and actually used. The Act
applies in stages, so the operator should use the European Commission's
[current implementation timeline](https://digital-strategy.ec.europa.eu/en/policies/regulatory-framework-ai)
rather than treating this document's date as a compliance calendar.

Before changing the intended use, record a new assessment covering the users,
affected people, decision impact, jurisdictions, data categories, model and
hosting arrangement, integrations, human oversight, and applicable sector
rules. A high-risk or regulated deployment needs specialist review and controls
beyond those documented here.

## NIST AI RMF alignment

This mapping uses the voluntary [NIST AI Risk Management Framework 1.0](https://www.nist.gov/itl/ai-risk-management-framework)
functions. “Alignment” means the project has related practices; it does not
mean NIST certification or full conformance.

| Function | Current evidence and control | Limitation or follow-up |
|---|---|---|
| **GOVERN** | This document defines intended use, excluded uses, accountable review, escalation triggers, and operator responsibilities. The read-only allowlist and bounded tool loop establish technical policy. Adversarial and regression cases are version-controlled. | Assign named business, risk, privacy, and security owners for each production deployment. Maintain an AI-system inventory, approvals, incident process, supplier/model due diligence, staff training, and periodic review records. |
| **MAP** | The architecture, data flows, local/default and hosted egress, retrieved documents, model, owner input, tool calls, and affected use cases are documented. The table above identifies contextual EU classification triggers and foreseeable failure modes. | Complete a deployment-specific impact assessment with stakeholders. Document data provenance, users and affected groups, misuse scenarios, local law, accessibility, bias pathways, and upstream/downstream dependencies. |
| **MEASURE** | Unit tests exercise guardrail rules. The adversarial suite covers direct prompt injection, hallucination bait, destructive-looking arguments, and credential terms. The regression suite measures grounding, citation validity, expected tool use, latency, and review outcomes. Structured traces can support investigation. | Current cases are small and synthetic; they do not measure demographic bias, privacy leakage, indirect injection, model extraction, factual accuracy across representative production data, calibration, or human outcomes. Establish release thresholds, a representative test set, red-team testing, false-positive/negative analysis, and drift monitoring for every supported model. |
| **MANAGE** | Ungrounded responses fail at the MCP boundary. Other suspicious results include deterministic review reasons. Calls are restricted to four read-only tools, capped, and recorded; operators can keep the default model and storage local. | Ensure the user interface visibly acts on `needs_review`; define stop/use and rollback criteria. Add incident reporting, remediation owners and deadlines, access controls, retention/deletion rules, monitoring alerts, model/version change control, and tested fallback procedures. |

### Evaluation coverage at a glance

| Evaluated risk | Existing coverage | What a passing case means |
|---|---|---|
| Direct prompt injection | “ignore previous,” role-switch, and model delimiter examples | The deterministic reviewer set `needs_review`; it does **not** show the model resisted the instruction. |
| Fabricated scenarios | “pretend” and “make up” examples | The request was flagged as hallucination bait. |
| Tool misuse | destructive-looking actions and a credential keyword | Recorded arguments were flagged. The separate allowlist is the control that prevents calls to unapproved tool names. |
| Grounding and citations | missing grounding, missing markers, dangling document markers, and citations to tools never called | Observable source/citation conditions were detected; semantic correctness still requires review. |
| Expected research behaviour | regression cases for expected tools, sources, and response properties | The configured stack met the encoded expectation for that run and environment, not all possible questions. |

Evaluation reports should record the code revision, model/provider and version,
configuration, dataset revision, date, aggregate results, failures, exceptions,
and approval decision. Re-run them before release when any of those inputs
materially changes.

## Operating responsibilities

### Before deployment

1. Confirm that the proposed use remains within the intended-use boundary and
   record the EU AI Act role/classification plus other applicable obligations.
2. Identify data owners and legal authority for every corpus and portfolio;
   remove secrets and unnecessary personal data.
3. Review model and observability providers, data locations, retention,
   training-on-input terms, security controls, and cross-border transfers.
4. Run unit, regression, and adversarial tests against the exact model and
   configuration; document acceptance thresholds and unresolved limitations.
5. Design the client so AI interaction and sources are apparent, warnings and
   `needs_review` cannot be mistaken for approval, and qualified human review
   occurs before consequential use.

### During operation

- retain only the minimum traces needed under a documented retention schedule;
  protect them because questions, tool arguments, excerpts, and answers can
  contain financial or personal information;
- restrict access by least privilege and validate owner/tenant isolation outside
  the model;
- monitor review rates, invalid citations, ungrounded failures, tool failures,
  user complaints, security events, drift, and material model/provider changes;
- give users a route to report errors and contest consequential reliance; and
- suspend the tool when controls, source integrity, or oversight are uncertain.

### Human review and incidents

A reviewer should read every `review_reasons` entry, open the cited source,
verify material facts and calculations, check freshness and ownership, and
consider missing or conflicting evidence. For high-consequence use, review is
required even when `needs_review=false`.

Treat suspected data exposure, cross-tenant retrieval, successful prompt
injection, unauthorised action, systematic harmful bias, or consequentially
false output as an incident. Preserve relevant evidence securely, stop or
isolate the affected path, notify the designated security/privacy/product
owners, assess notification obligations, remediate, and add a regression test
before re-enabling it. Do not put credentials or additional sensitive data into
an issue or evaluation fixture.

## Evidence locations

- `research-agent/app/guardrails.py` — deterministic review checks and reasons.
- `research-agent/app/mcp_tools.py` — tool allowlist enforcement and call record.
- `research-agent/app/agent.py` — grounding, citation warnings, and review
  integration.
- `research-agent/eval/adversarial.yaml` — documented adversarial scenarios.
- `research-agent/eval/regression.yaml` — expected-behaviour scenarios.
- `research-agent/run_eval.py` — evaluation runner and reports.
- `research-agent/tests/test_guardrails.py` — executable guardrail tests.
- `research-agent/README.md` — architecture, configuration, egress, tracing, and
  test instructions.

This evidence supports governance review but is not proof that a particular
deployment complies with law or is safe for a use outside this document.
