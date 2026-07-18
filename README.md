[![Syntax Status](https://github.com/openemr/openemr/actions/workflows/syntax.yml/badge.svg)](https://github.com/openemr/openemr/actions/workflows/syntax.yml)
[![Styling Status](https://github.com/openemr/openemr/actions/workflows/styling.yml/badge.svg)](https://github.com/openemr/openemr/actions/workflows/styling.yml)
[![Testing Status](https://github.com/openemr/openemr/actions/workflows/test.yml/badge.svg)](https://github.com/openemr/openemr/actions/workflows/test.yml)
[![JS Unit Testing Status](https://github.com/openemr/openemr/actions/workflows/js-test.yml/badge.svg)](https://github.com/openemr/openemr/actions/workflows/js-test.yml)
[![PHPStan](https://github.com/openemr/openemr/actions/workflows/phpstan.yml/badge.svg)](https://github.com/openemr/openemr/actions/workflows/phpstan.yml)
[![Rector](https://github.com/openemr/openemr/actions/workflows/rector.yml/badge.svg)](https://github.com/openemr/openemr/actions/workflows/rector.yml)
[![ShellCheck](https://github.com/openemr/openemr/actions/workflows/shellcheck.yml/badge.svg)](https://github.com/openemr/openemr/actions/workflows/shellcheck.yml)
[![Docker Compose Linting](https://github.com/openemr/openemr/actions/workflows/docker-compose-lint.yml/badge.svg)](https://github.com/openemr/openemr/actions/workflows/docker-compose-lint.yml)
[![Dockerfile Linting](https://github.com/openemr/openemr/actions/workflows/docker-lint-hadolint.yml/badge.svg)](https://github.com/openemr/openemr/actions/workflows/docker-lint-hadolint.yml)
[![Isolated Tests](https://github.com/openemr/openemr/actions/workflows/isolated-tests.yml/badge.svg)](https://github.com/openemr/openemr/actions/workflows/isolated-tests.yml)
[![Inferno Certification Test](https://github.com/openemr/openemr/actions/workflows/inferno-test.yml/badge.svg)](https://github.com/openemr/openemr/actions/workflows/inferno-test.yml)
[![Composer Checks](https://github.com/openemr/openemr/actions/workflows/composer.yml/badge.svg)](https://github.com/openemr/openemr/actions/workflows/composer.yml)
[![Composer Require Checker](https://github.com/openemr/openemr/actions/workflows/composer-require-checker.yml/badge.svg)](https://github.com/openemr/openemr/actions/workflows/composer-require-checker.yml)
[![API Docs Freshness Checks](https://github.com/openemr/openemr/actions/workflows/api-docs.yml/badge.svg)](https://github.com/openemr/openemr/actions/workflows/api-docs.yml)
[![codecov](https://codecov.io/gh/openemr/openemr/graph/badge.svg?token=7Eu3U1Ozdq)](https://codecov.io/gh/openemr/openemr)

[![Backers on Open Collective](https://opencollective.com/openemr/backers/badge.svg)](#backers) [![Sponsors on Open Collective](https://opencollective.com/openemr/sponsors/badge.svg)](#sponsors)

# OpenEMR Agent Forge

Deployed demo viewable [here](https://truthful-peace-production-62af.up.railway.app/)\
Ready Status [here](https://ai-sidecar-production-c492.up.railway.app/ready)\
Health Check [here](https://ai-sidecar-production-c492.up.railway.app/health)\
Live Metrics Snapshot [here](https://ai-sidecar-production-c492.up.railway.app/metrics)

## Contents
[Installation](#installation)\
[Environment Variables](#environment-variables)\
[Architecture Diagram](#architecture-diagram)\
[Engineering Deliverables](#engineering-deliverables)\
[Week 1 Submission Requirements](#week-1-submission-requirements)\
[Week 2 Submission Requirements](#week-2-submission-requirements) 

## Installation

Follow the full local setup documentation [here](SETUP.md)

## Environment Variables

### .env
```bash
ANTHROPIC_API_KEY=
GITLAB_CLONE_URL=
GITLAB_CLONE_USERNAME=
GITLAB_CLONE_TOKEN=
```
### sidecar/.env
```bash
ANTHROPIC_API_KEY=
BRAINTRUST_API_KEY=
COHERE_API_KEY=

# Local Qdrant dense-store — dockerized qdrant/qdrant
QDRANT_URL=http://localhost:6333
OE_AI_AGENT_SIGNING_KEY=
```
## Architecture Diagram

Week 1 [here](W!_ARCHITECTURE_DIAGRAM.md)\
Week 2 [here](W2_ARCHITECTURE_DIAGRAM.md)

## Engineering Deliverables
Postman Collection and Environment [here](/postman/)\
Braintrust alerts x5 are document with on-call responses [here](ALERTS.md)\
Week 1 Infrastructure Metrics [here](METRICS_WEEK1.md)\
Stress Test results [here](STRESS_TESTS.md)

## Week 1 Submission Requirements
Eval dataset [here](EVAL_DATASET.md)\
AI Cost Analysis [here](COST_ANALYSIS.md)

## Week 2 Submission Requirements
Latency and Cost report [here](COST_ANALYSIS_W2_MVP.md)\
Lab Report [here](/sidecar/fixtures/documents/synthetic_lab_report.pdf)\
Intake Form [here](/sidecar/fixtures/documents/synthetic_intake_form_match.png)\
Intake Form (Incorrect Patient) [here](/sidecar/fixtures/documents/synthetic_intake_form.png)\
Intake Form (Noisy scan) [here](/sidecar/fixtures/documents/synthetic_intake_form_noisy.png)\
Architecture [here](W2_ARCHITECTURE.md)\
Schemas [here](W2_SCHEMAS.md)\
Eval Dataset [here](EVAL_DATASET_W2.md)\
CI Evidence [here](W2_CI_EVIDENCE.md)\
Cost and Latency Report [here](COST_ANALYSIS_W2_FINAL.md)