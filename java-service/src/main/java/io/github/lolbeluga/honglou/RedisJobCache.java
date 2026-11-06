package io.github.lolbeluga.honglou;

import java.time.Duration;
import java.util.Optional;
import java.util.concurrent.ThreadLocalRandom;
import java.util.concurrent.atomic.AtomicLong;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Component;
import tools.jackson.databind.json.JsonMapper;

@Component
@ConditionalOnProperty(name="research.cache.enabled", havingValue="true")
public class RedisJobCache implements JobResultCache {
    private final StringRedisTemplate redis;
    private final String namespace;
    private final int ttl, jitter, negativeTtl;
    private final JsonMapper json = JsonMapper.builder().build();
    private final AtomicLong bypassUntil = new AtomicLong();

    public RedisJobCache(StringRedisTemplate redis,
            @Value("${research.cache.namespace}") String namespace,
            @Value("${research.cache.ttl-seconds}") int ttl,
            @Value("${research.cache.jitter-seconds}") int jitter,
            @Value("${research.cache.negative-ttl-seconds}") int negativeTtl) {
        if (namespace.isBlank() || ttl < 1 || jitter < 0 || negativeTtl < 1)
            throw new IllegalArgumentException("Invalid cache configuration");
        this.redis = redis;
        this.namespace = namespace;
        this.ttl = ttl;
        this.jitter = jitter;
        this.negativeTtl = negativeTtl;
    }
    public Optional<Entry> read(String id) {
        if (System.nanoTime() < bypassUntil.get()) return Optional.empty();
        try {
            String raw = redis.opsForValue().get(namespace + id);
            if (raw == null) return Optional.empty();
            Entry entry = json.readValue(raw, Entry.class);
            if (entry == null || (entry.job() != null &&
                    (!entry.job().id().equals(id) || !entry.job().status().equals("COMPLETED")))) {
                redis.delete(namespace + id);
                return Optional.empty();
            }
            return Optional.of(entry);
        } catch (RuntimeException failure) {
            bypass(failure);
            return Optional.empty();
        }
    }
    public void write(String id, Job job) {
        if (job != null && (!job.status().equals("COMPLETED") || !job.id().equals(id))) return;
        if (System.nanoTime() < bypassUntil.get()) return;
        try {
            long seconds = job == null ? negativeTtl : ttl + ThreadLocalRandom.current().nextLong((long) jitter + 1);
            redis.opsForValue().set(namespace + id, json.writeValueAsString(new Entry(job)), Duration.ofSeconds(seconds));
        } catch (RuntimeException failure) {
            bypass(failure);
        }
    }
    private void bypass(RuntimeException failure) {
        long now = System.nanoTime();
        long previous = bypassUntil.get();
        if (now >= previous && bypassUntil.compareAndSet(previous, now + Duration.ofSeconds(5).toNanos()))
            LoggerFactory.getLogger(RedisJobCache.class).warn("Redis cache bypassed for 5s ({})", failure.getClass().getSimpleName());
    }
}
