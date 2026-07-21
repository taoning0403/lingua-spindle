ALTER TABLE translation_segments
ADD COLUMN segment_key VARCHAR(64);

CREATE UNIQUE INDEX ix_segments_job_segment_key
ON translation_segments(job_id, segment_key)
WHERE segment_key IS NOT NULL;
