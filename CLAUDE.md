# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working in this repository.

## Project Overview

This is a **POC specification** for a Pharmaceutical Representative AI Assistant. The primary artifact is `PharmaceuticalRepresentativeAIAssistant.md`, which defines system requirements, data schemas, and behavioral contracts for an AI-powered doctor information retrieval system.

No implementation exists yet — this is the design/planning phase.

## Project Goal

Build an AI assistant that aggregates doctor-related data from three data sources and returns accurate, structured, traceable responses to pharmaceutical reps. The assistant must never hallucinate or infer data.

## Data Model

Three tables linked by `Medical License Number` (the doctor identifier):

- **Personal Details** — name, contact, address fields
- **License Details** — tenure, expiry date (FK: Medical License Number)
- **Drug Purchase Details** — drug ID, name, brand, purchase date, quantity, amount (FK: Medical License Number)

## Core Behavioral Constraints (from spec)

- **No hallucinations**: if data is unavailable, respond with `"The requested data is not available in the current data sources."`
- **Source traceability**: every response must include table name, field references, and record ID when available
- **Accuracy over speed**: latency target is <10ms but never at the cost of correctness
- **Structured output**: responses follow the format defined in the spec (Doctor, Location, License, Recent Drug Purchases, Source sections)

## Supported Query Types

1. General doctor lookup (personal + license + drug history)
2. Attribute-based filtering (license number, name, location, drug/brand, license expiry)
3. Multimodal input (voice transcribed to text before processing)

## When Implementing

- The spec in `PharmaceuticalRepresentativeAIAssistant.md` is the source of truth for all behavioral requirements
- Health data privacy standards apply to all field exposure decisions
- Only return authorized fields; avoid unnecessary exposure of personal data
- Future extensions (prescribing patterns, CRM integration, sales ranking) are noted in the spec but out of scope for initial POC
