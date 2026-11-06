package io.github.lolbeluga.honglou;

import java.util.List;
import java.util.Optional;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.stereotype.Repository;
import org.springframework.transaction.annotation.Transactional;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

@Repository
public class JobRepository {
    private final JdbcTemplate db;
    private final JsonMapper json = JsonMapper.builder().build();
    private final RowMapper<Job> mapper = (r, n) -> new Job(r.getString("id"),
        r.getString("question"), r.getString("mode"), r.getString("status"), r.getInt("attempt"),
        r.getString("result_json") == null ? null : json.readTree(r.getString("result_json")),
        r.getString("error_message"), r.getLong("created_at"), r.getLong("updated_at"));

    public JobRepository(JdbcTemplate db) { this.db = db; }
    public Optional<Job> find(String id) {
        return db.query("SELECT * FROM research_jobs WHERE id=?", mapper, id).stream().findFirst();
    }
    public Optional<Job> byKey(String key) {
        return db.query("SELECT * FROM research_jobs WHERE request_key=?", mapper, key).stream().findFirst();
    }
    public List<Job> recent(int limit) {
        return db.query("SELECT id,question,mode,status,attempt,NULL AS result_json,error_message,created_at,updated_at FROM research_jobs ORDER BY created_at DESC,id LIMIT ?", mapper, limit);
    }
    @Transactional
    public Job insert(String id, String key, String question, String mode) {
        long now = System.currentTimeMillis();
        db.update("INSERT INTO research_jobs(id,request_key,question,mode,status,attempt,created_at,updated_at) VALUES(?,?,?,?,'QUEUED',1,?,?)",
                  id, key, question, mode, now, now);
        return find(id).orElseThrow();
    }
    public boolean claim(String id, int attempt) {
        return db.update("UPDATE research_jobs SET status='RUNNING',updated_at=? WHERE id=? AND attempt=? AND status='QUEUED'",
                         System.currentTimeMillis(), id, attempt) == 1;
    }
    public boolean retry(Job job) {
        return db.update("UPDATE research_jobs SET status='QUEUED',attempt=attempt+1,error_message=NULL,updated_at=? WHERE id=? AND attempt=? AND status IN ('FAILED','PAUSED','INTERRUPTED')",
                         System.currentTimeMillis(), job.id(), job.attempt()) == 1;
    }
    public void finish(String id, int attempt, String status, JsonNode result, String error) {
        db.update("UPDATE research_jobs SET status=?,result_json=?,error_message=?,updated_at=? WHERE id=? AND attempt=? AND status IN ('QUEUED','RUNNING')",
            status, result == null ? null : json.writeValueAsString(result), error,
            System.currentTimeMillis(), id, attempt);
    }
    public void interruptUnfinished() {
        db.update("UPDATE research_jobs SET status='INTERRUPTED',error_message='服务重启，请检查后重试；不会自动追加模型请求。',updated_at=? WHERE status IN ('QUEUED','RUNNING')",
                  System.currentTimeMillis());
    }
}
