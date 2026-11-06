CREATE TABLE IF NOT EXISTS research_jobs (
    id VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
    request_key VARCHAR(128) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    question VARCHAR(2000) NOT NULL,
    mode VARCHAR(16) NOT NULL,
    status VARCHAR(20) NOT NULL,
    attempt INT NOT NULL,
    result_json JSON,
    error_message VARCHAR(500),
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    UNIQUE KEY uk_jobs_request_key (request_key),
    KEY idx_jobs_created (created_at DESC, id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
