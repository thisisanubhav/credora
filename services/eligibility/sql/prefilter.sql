-- Candidate pairs for one bounded user-ID page; product rules are rechecked in Python.
WITH page_users AS MATERIALIZED (
    SELECT u.*
    FROM unnest(CAST(:user_ids AS uuid[])) AS selected(id)
    JOIN users AS u ON u.id = selected.id
    WHERE u.upload_batch_id = :batch_id
)
SELECT
    u.id AS user_id, u.upload_batch_id AS batch_id, u.monthly_income,
    u.income_currency, u.credit_score, u.age, u.employment_status,
    p.id AS product_id, p.version, p.currency_code, p.criterion_states,
    p.eligibility_rules, p.verification_status, p.is_current,
    p.retired_at IS NOT NULL AS retired, s.source_type
FROM page_users AS u
JOIN loan_products AS p ON p.is_current
    AND p.verification_status = 'verified'
    AND p.retired_at IS NULL
    AND p.rule_schema_version = 1
    AND (p.min_age IS NULL OR u.age >= p.min_age)
    AND (p.max_age IS NULL OR u.age <= p.max_age)
    AND (p.min_credit_score IS NULL OR u.credit_score >= p.min_credit_score)
    AND (p.max_credit_score IS NULL OR u.credit_score <= p.max_credit_score)
    AND (p.min_monthly_income IS NULL OR (
        u.income_currency IS NOT NULL AND p.currency_code IS NOT NULL
        AND u.income_currency = p.currency_code
        AND u.monthly_income >= p.min_monthly_income
    ))
    AND (p.eligible_employment_statuses IS NULL OR (
        u.employment_status <> 'other'
        AND u.employment_status = ANY(p.eligible_employment_statuses)
    ))
JOIN product_sources AS s ON s.id = p.source_id
    AND (s.source_type = 'official' OR (:demo_batch AND s.source_type = 'synthetic'))
ORDER BY u.id, p.id
