ALTER TABLE sources
ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}';

ALTER TABLE translation_segments
ADD COLUMN source_artifact_id VARCHAR(36)
REFERENCES artifacts(id) ON DELETE SET NULL;

ALTER TABLE translation_segments
ADD COLUMN source_document TEXT;

ALTER TABLE translation_segments
ADD COLUMN content_role VARCHAR(40);

ALTER TABLE translation_segments
ADD COLUMN locator_json TEXT NOT NULL DEFAULT '{}';

ALTER TABLE translation_segments
ADD COLUMN source_text_hash VARCHAR(64);

ALTER TABLE translation_segments
ADD COLUMN translation_input_hash VARCHAR(64);

ALTER TABLE translation_segments
ADD COLUMN reused_from_segment_id VARCHAR(36)
REFERENCES translation_segments(id) ON DELETE SET NULL;

CREATE INDEX ix_segments_project_input_hash
ON translation_segments(project_id, translation_input_hash, status);

CREATE INDEX ix_segments_job_document
ON translation_segments(job_id, source_document, sequence);
