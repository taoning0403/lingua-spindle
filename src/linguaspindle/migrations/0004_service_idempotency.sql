ALTER TABLE jobs
ADD COLUMN execution_fingerprint VARCHAR(96);

ALTER TABLE jobs
ADD COLUMN request_id VARCHAR(128);

CREATE UNIQUE INDEX uq_jobs_active_execution_fingerprint
ON jobs(execution_fingerprint)
WHERE execution_fingerprint IS NOT NULL
  AND status IN ('queued', 'running', 'paused', 'cancelling');

CREATE TABLE idempotency_records (
    id VARCHAR(36) PRIMARY KEY,
    scope VARCHAR(200) NOT NULL,
    key_hash VARCHAR(64) NOT NULL,
    request_fingerprint VARCHAR(96) NOT NULL,
    status VARCHAR(20) NOT NULL
        CHECK(status IN ('processing', 'completed', 'failed', 'indeterminate')),
    resource_type VARCHAR(40),
    resource_id VARCHAR(64),
    response_status INTEGER,
    result_reference_json TEXT NOT NULL DEFAULT '{}',
    request_id VARCHAR(128) NOT NULL,
    error_code VARCHAR(80),
    error_message TEXT,
    error_details_json TEXT,
    error_retryable INTEGER NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    CONSTRAINT uq_idempotency_scope_key_hash UNIQUE(scope, key_hash)
);

CREATE INDEX ix_idempotency_records_status
ON idempotency_records(status);

CREATE INDEX ix_idempotency_records_resource_id
ON idempotency_records(resource_id);
