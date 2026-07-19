CREATE TABLE projects (
    id VARCHAR(36) PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    kind VARCHAR(20) NOT NULL,
    source_language VARCHAR(40) NOT NULL,
    target_language VARCHAR(40) NOT NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL
);
CREATE INDEX ix_projects_kind ON projects(kind);

CREATE TABLE translation_profiles (
    id VARCHAR(36) PRIMARY KEY,
    name VARCHAR(120) NOT NULL,
    source_language VARCHAR(40) NOT NULL,
    target_language VARCHAR(40) NOT NULL,
    provider_id VARCHAR(80) NOT NULL,
    model VARCHAR(160) NOT NULL,
    style TEXT NOT NULL,
    context_strategy VARCHAR(80) NOT NULL,
    prompt_template TEXT NOT NULL,
    prompt_version VARCHAR(40) NOT NULL,
    batch_size INTEGER NOT NULL,
    model_parameters_json TEXT NOT NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL
);

CREATE TABLE provider_configs (
    id VARCHAR(80) PRIMARY KEY,
    base_url VARCHAR(500) NOT NULL,
    model VARCHAR(160) NOT NULL,
    timeout_seconds FLOAT NOT NULL,
    concurrency_limit INTEGER NOT NULL,
    max_retries INTEGER NOT NULL,
    updated_at DATETIME NOT NULL
);

CREATE TABLE jobs (
    id VARCHAR(36) PRIMARY KEY,
    project_id VARCHAR(36) NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    translation_profile_id VARCHAR(36) REFERENCES translation_profiles(id) ON DELETE SET NULL,
    pipeline_key VARCHAR(80) NOT NULL,
    pipeline_version VARCHAR(40) NOT NULL,
    provider_id VARCHAR(80) NOT NULL,
    adapter_id VARCHAR(120),
    status VARCHAR(40) NOT NULL,
    progress FLOAT NOT NULL,
    control_request VARCHAR(40),
    profile_snapshot_json TEXT NOT NULL,
    requested_at DATETIME NOT NULL,
    started_at DATETIME,
    ended_at DATETIME,
    updated_at DATETIME NOT NULL,
    runner_token VARCHAR(36),
    error_code VARCHAR(80),
    error_message TEXT,
    error_details_json TEXT
);
CREATE INDEX ix_jobs_project_id ON jobs(project_id);
CREATE INDEX ix_jobs_status ON jobs(status);
CREATE INDEX ix_jobs_runner_token ON jobs(runner_token);

CREATE TABLE step_runs (
    id VARCHAR(36) PRIMARY KEY,
    job_id VARCHAR(36) NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    step_key VARCHAR(80) NOT NULL,
    step_order INTEGER NOT NULL,
    capability VARCHAR(80) NOT NULL,
    executor_type VARCHAR(40) NOT NULL,
    executor_id VARCHAR(120),
    status VARCHAR(40) NOT NULL,
    attempt_count INTEGER NOT NULL,
    started_at DATETIME,
    ended_at DATETIME,
    progress FLOAT NOT NULL,
    input_artifact_ids_json TEXT NOT NULL,
    output_artifact_ids_json TEXT NOT NULL,
    config_snapshot_json TEXT NOT NULL,
    error_code VARCHAR(80),
    error_message TEXT,
    error_details_json TEXT,
    CONSTRAINT uq_step_job_key UNIQUE(job_id, step_key)
);
CREATE INDEX ix_step_runs_job_id ON step_runs(job_id);
CREATE INDEX ix_step_runs_status ON step_runs(status);

CREATE TABLE artifacts (
    id VARCHAR(36) PRIMARY KEY,
    project_id VARCHAR(36) NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    job_id VARCHAR(36) REFERENCES jobs(id) ON DELETE CASCADE,
    step_run_id VARCHAR(36) REFERENCES step_runs(id) ON DELETE SET NULL,
    kind VARCHAR(80) NOT NULL,
    filename VARCHAR(255) NOT NULL,
    media_type VARCHAR(120) NOT NULL,
    size INTEGER NOT NULL,
    checksum VARCHAR(64) NOT NULL,
    storage_key VARCHAR(500) NOT NULL UNIQUE,
    metadata_json TEXT NOT NULL,
    created_at DATETIME NOT NULL
);
CREATE INDEX ix_artifacts_project_id ON artifacts(project_id);
CREATE INDEX ix_artifacts_job_id ON artifacts(job_id);
CREATE INDEX ix_artifacts_step_run_id ON artifacts(step_run_id);
CREATE INDEX ix_artifacts_kind ON artifacts(kind);

CREATE TABLE sources (
    id VARCHAR(36) PRIMARY KEY,
    project_id VARCHAR(36) NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    kind VARCHAR(40) NOT NULL,
    original_name VARCHAR(255) NOT NULL,
    media_type VARCHAR(120) NOT NULL,
    size INTEGER NOT NULL,
    checksum VARCHAR(64) NOT NULL,
    artifact_id VARCHAR(36) NOT NULL REFERENCES artifacts(id) ON DELETE RESTRICT,
    created_at DATETIME NOT NULL
);
CREATE INDEX ix_sources_project_id ON sources(project_id);

CREATE TABLE step_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id VARCHAR(36) NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    step_run_id VARCHAR(36) NOT NULL REFERENCES step_runs(id) ON DELETE CASCADE,
    level VARCHAR(20) NOT NULL,
    message TEXT NOT NULL,
    details_json TEXT NOT NULL,
    created_at DATETIME NOT NULL
);
CREATE INDEX ix_step_logs_job_id ON step_logs(job_id);
CREATE INDEX ix_step_logs_step_run_id ON step_logs(step_run_id);

CREATE TABLE translation_segments (
    id VARCHAR(36) PRIMARY KEY,
    project_id VARCHAR(36) NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    job_id VARCHAR(36) NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL,
    source_text TEXT NOT NULL,
    translated_text TEXT,
    status VARCHAR(40) NOT NULL,
    model VARCHAR(160),
    profile_snapshot_json TEXT NOT NULL,
    prompt_version VARCHAR(40) NOT NULL,
    error_code VARCHAR(80),
    error_message TEXT,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    CONSTRAINT uq_segment_job_sequence UNIQUE(job_id, sequence)
);
CREATE INDEX ix_translation_segments_project_id ON translation_segments(project_id);
CREATE INDEX ix_translation_segments_job_id ON translation_segments(job_id);
CREATE INDEX ix_translation_segments_status ON translation_segments(status);

CREATE TABLE qa_findings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id VARCHAR(36) NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    job_id VARCHAR(36) NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    segment_id VARCHAR(36) REFERENCES translation_segments(id) ON DELETE CASCADE,
    category VARCHAR(80) NOT NULL,
    severity VARCHAR(20) NOT NULL,
    message TEXT NOT NULL,
    created_at DATETIME NOT NULL
);
CREATE INDEX ix_qa_findings_project_id ON qa_findings(project_id);
CREATE INDEX ix_qa_findings_job_id ON qa_findings(job_id);
CREATE INDEX ix_qa_findings_segment_id ON qa_findings(segment_id);
