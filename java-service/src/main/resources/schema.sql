CREATE TABLE IF NOT EXISTS research_jobs (
    id VARCHAR(32) PRIMARY KEY,
    request_key VARCHAR(128) NOT NULL UNIQUE,
    question VARCHAR(2000) NOT NULL,
    mode VARCHAR(16) NOT NULL,
    status VARCHAR(20) NOT NULL,
    attempt INT NOT NULL,
    result_json CLOB,
    error_message VARCHAR(500),
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_created ON research_jobs(created_at DESC, id);
