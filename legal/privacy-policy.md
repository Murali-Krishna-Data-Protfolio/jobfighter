# Privacy Policy — DRAFT, NOT LEGAL ADVICE

> **This is a starting template only.** It was written to match the data
> model in `docs/architecture.md`, not reviewed by a lawyer. Have this
> reviewed against your actual jurisdiction, hosting setup, and any
> applicable law (GDPR if serving EU users, etc.) before relying on it for
> a real public product. Replace every `[bracketed]` placeholder.

**Last updated:** [date]
**Controller:** [your name / entity], [contact email]

## What we collect

- **Account data**: your email address (used only for magic-link login and
  the job digest email).
- **Candidate profile**: name, education, location, target roles, skills,
  salary expectations, notification email — whatever you enter into your
  profile to run job searches.
- **Your tracked jobs**: which job postings you've saved, their status
  (Saved/Applied/Interview/Offer/Rejected), and any private notes you add.
- **Job postings themselves** (titles, companies, descriptions, URLs) are
  **public data**, sourced from public job boards/APIs — not personal data
  about you, and stored separately from your account (see
  `docs/architecture.md` §Multi-Tenant Data Model).

## What we do not collect

We do not collect passwords (login is passwordless, via emailed link). We
do not sell or share your personal data with third parties beyond what's
strictly needed to run the service (e.g., the transactional email provider
that sends your login link and digest).

## How we use it

Solely to run the job-tracking service you signed up for: fetching and
classifying jobs against your profile's criteria, sending you your login
link and digest email, and letting you manage your own tracked jobs.

## Retention & deletion

You can delete your account at any time from [settings page]. This
permanently removes your `candidate_profiles`, `tracked_jobs`, and `runs`
data. It does **not** remove the underlying job postings themselves (they
are public data, not tied to your account, and other users may still be
tracking them).

## Your rights

Depending on your jurisdiction, you may have the right to access, correct,
export, or delete your personal data. Contact [email] to exercise these
rights.

## Third parties

- **[Hosting provider]** — hosts the application and database.
- **[Transactional email provider]** — sends login links and digest emails.
- **Anthropic (Claude API)** — job posting text is sent to Claude to
  classify its language; your personal profile data is used only to build
  context for that classification and is not otherwise shared with
  Anthropic beyond what's needed for the API call.

## Changes

We may update this policy; material changes will be [notified via email /
posted here] with an updated date at the top.
