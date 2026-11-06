package io.github.lolbeluga.honglou;

import java.util.UUID;
import java.util.concurrent.*;
import java.net.ServerSocket;
import java.time.Duration;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.context.annotation.Primary;
import org.springframework.data.redis.connection.RedisStandaloneConfiguration;
import org.springframework.data.redis.connection.lettuce.LettuceClientConfiguration;
import org.springframework.data.redis.connection.lettuce.LettuceConnectionFactory;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.web.server.ResponseStatusException;
import tools.jackson.databind.json.JsonMapper;
import static org.junit.jupiter.api.Assertions.*;

@EnabledIfEnvironmentVariable(named="HONGLOU_INTEGRATION", matches="true")
@SpringBootTest(properties={"spring.profiles.active=mysql","research.cache.enabled=true"})
@Import(MySqlRedisIntegrationTest.Workers.class)
class MySqlRedisIntegrationTest {
    static final String prefix = "honglou:integration:" + UUID.randomUUID() + ":";
    @DynamicPropertySource static void properties(DynamicPropertyRegistry registry) {
        registry.add("research.cache.namespace", () -> prefix);
    }
    @Autowired JobRepository jobs;
    @Autowired JobService service;
    @Autowired JobQueryService queries;
    @Autowired StringRedisTemplate redis;
    @TestConfiguration static class Workers {
        @Bean @Primary WorkerRunner testWorker() {
            return (job, extended) -> JsonMapper.builder().build().readTree("{\"status\":\"completed\",\"answer\":\"原文🌸\"}");
        }
    }
    String id() { return UUID.randomUUID().toString().replace("-",""); }
    Job complete() {
        var job = jobs.insert(id(), UUID.randomUUID().toString(), "黛玉🌸葬花", "lookup");
        jobs.claim(job.id(),1);
        jobs.finish(job.id(),1,"COMPLETED",JsonMapper.builder().build().readTree("{\"answer\":\"花谢花飞🌸\"}"),null);
        return jobs.find(job.id()).orElseThrow();
    }
    @Test void mysqlPreservesUnicodeJsonAndCaseSensitiveRequestKeys() {
        var job = complete();
        assertEquals("黛玉🌸葬花",job.question());
        assertEquals("花谢花飞🌸",job.result().path("answer").asText());
        String key = "Key-" + UUID.randomUUID();
        jobs.insert(id(),key,"一","lookup");
        jobs.insert(id(),key.toLowerCase(),"二","lookup");
        assertThrows(DuplicateKeyException.class,() -> jobs.insert(id(),key,"三","lookup"));
    }
    @Test void mysqlConcurrentReplayCreatesOneTask() throws Exception {
        String key = UUID.randomUUID().toString();
        try (var clients = Executors.newFixedThreadPool(6)) {
            var tasks = java.util.stream.IntStream.range(0,6).mapToObj(i ->
                (Callable<String>) () -> service.submit(key,"宝玉","lookup").job().id()).toList();
            var responses = clients.invokeAll(tasks);
            String first = responses.getFirst().get();
            for (var response : responses) assertEquals(first,response.get());
        }
    }
    @Test void realRedisStoresCompletedResultsAndExpiresThem() throws Exception {
        var job = complete();
        assertEquals(job,queries.get(job.id()));
        assertTrue(Boolean.TRUE.equals(redis.hasKey(prefix + job.id())));
        long ttl = redis.getExpire(prefix + job.id());
        assertTrue(ttl > 0 && ttl <= 1020);
        redis.expire(prefix + job.id(),Duration.ofMillis(50));
        Thread.sleep(100);
        assertFalse(Boolean.TRUE.equals(redis.hasKey(prefix + job.id())));
        assertEquals(job,queries.get(job.id()));
        assertTrue(Boolean.TRUE.equals(redis.hasKey(prefix + job.id())));
    }
    @Test void nonexistentJobHasShortTtlButPausedStatusIsNotCached() {
        String missing = id();
        assertThrows(ResponseStatusException.class,() -> queries.get(missing));
        assertTrue(redis.getExpire(prefix + missing) > 0 && redis.getExpire(prefix + missing) <= 30);
        var job = jobs.insert(id(),UUID.randomUUID().toString(),"宝钗","research");
        jobs.finish(job.id(),1,"PAUSED",null,null);
        assertEquals("PAUSED",queries.get(job.id()).status());
        assertFalse(Boolean.TRUE.equals(redis.hasKey(prefix + job.id())));
    }
    @Test void unavailableRedisStillReturnsMysqlResult() throws Exception {
        int unavailablePort;
        try (var socket = new ServerSocket(0)) { unavailablePort = socket.getLocalPort(); }
        var config = new RedisStandaloneConfiguration("127.0.0.1", unavailablePort);
        var client = LettuceClientConfiguration.builder().commandTimeout(Duration.ofMillis(200)).build();
        var connection = new LettuceConnectionFactory(config,client);
        connection.afterPropertiesSet();
        try {
            var template = new StringRedisTemplate(connection);
            var fallback = new JobQueryService(jobs,new RedisJobCache(template,prefix,900,0,30));
            var job = complete();
            assertEquals(job,fallback.get(job.id()));
        } finally { connection.destroy(); }
    }
}
