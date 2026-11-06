package io.github.lolbeluga.honglou;

import java.time.Duration;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.jdbc.datasource.init.ResourceDatabasePopulator;
import org.springframework.core.io.ClassPathResource;
import org.springframework.web.server.ResponseStatusException;
import tools.jackson.databind.json.JsonMapper;
import static org.junit.jupiter.api.Assertions.*;

class JobServiceTest {
    JobRepository repository() {
        var source = new DriverManagerDataSource("jdbc:h2:mem:"+UUID.randomUUID()+";DB_CLOSE_DELAY=-1", "sa", "");
        new ResourceDatabasePopulator(new ClassPathResource("schema.sql")).execute(source);
        return new JobRepository(new JdbcTemplate(source));
    }
    WorkerRunner completing(AtomicInteger calls) {
        return (job, extended) -> {calls.incrementAndGet();return JsonMapper.builder().build().readTree("{\"status\":\"completed\"}");};
    }
    void await(JobRepository repo, String id, String status) throws Exception {
        long end=System.nanoTime()+Duration.ofSeconds(5).toNanos();
        while(System.nanoTime()<end){if(repo.find(id).orElseThrow().status().equals(status))return;Thread.sleep(10);}
        fail("Expected "+status+", got "+repo.find(id));
    }
    @Test void concurrentSameKeyCreatesAndRunsOnlyOnce() throws Exception {
        var repo=repository();var calls=new AtomicInteger();var service=new JobService(repo,completing(calls),2,16);
        try(var clients=Executors.newFixedThreadPool(8)) {
            var tasks=java.util.stream.IntStream.range(0,8).mapToObj(i -> (Callable<String>) () -> service.submit("same-key-12345678","黛玉","lookup").job().id()).toList();
            var responses=clients.invokeAll(tasks);String id=responses.getFirst().get();
            for(var response:responses)assertEquals(id,response.get());
            await(repo,id,"COMPLETED");assertEquals(1,calls.get());assertEquals(1,repo.recent(20).size());
            assertEquals(409,assertThrows(ResponseStatusException.class,()->service.submit("same-key-12345678","宝钗","lookup")).getStatusCode().value());
        } finally {service.close();}
    }
    @Test void boundedQueueRejectsWithoutCreatingPhantomJob() throws Exception {
        var repo=repository();var entered=new CountDownLatch(1);var release=new CountDownLatch(1);
        var service=new JobService(repo,(job,extended)->{entered.countDown();release.await();return JsonMapper.builder().build().readTree("{\"status\":\"completed\"}");},1,1);
        try {
            service.submit("request-key-11111","一","lookup");assertTrue(entered.await(3,TimeUnit.SECONDS));
            service.submit("request-key-22222","二","lookup");
            assertEquals(429,assertThrows(ResponseStatusException.class,()->service.submit("request-key-33333","三","lookup")).getStatusCode().value());
            assertEquals(2,repo.recent(20).size());
            assertTrue(service.submit("request-key-11111","一","lookup").replayed());
        }finally{release.countDown();service.close();}
    }
    @Test void failureCanRetryButCompletedCannot() throws Exception {
        var repo=repository();var calls=new AtomicInteger();
        var service=new JobService(repo,(job,extended)->{if(calls.incrementAndGet()==1)throw new IllegalStateException();return JsonMapper.builder().build().readTree("{\"status\":\"completed\"}");},1,2);
        try {
            var job=service.submit("retry-key-1234567","黛玉","research").job();await(repo,job.id(),"FAILED");
            assertEquals(2,service.retry(job.id(),false).attempt());await(repo,job.id(),"COMPLETED");
            assertEquals(409,assertThrows(ResponseStatusException.class,()->service.retry(job.id(),false)).getStatusCode().value());
        }finally{service.close();}
    }
    @Test void restartMarksPendingAndRejectsStaleCompletion() {
        var repo=repository();var job=repo.insert("a".repeat(32),"key-restart-12345","黛玉","research");repo.claim(job.id(),1);
        var calls=new AtomicInteger();var service=new JobService(repo,completing(calls),1,1);
        try {
            assertEquals("INTERRUPTED",repo.find(job.id()).orElseThrow().status());assertEquals(0,calls.get());
            assertTrue(repo.retry(repo.find(job.id()).orElseThrow()));
            repo.finish(job.id(),1,"COMPLETED",null,null);
            assertEquals("QUEUED",repo.find(job.id()).orElseThrow().status());
        }finally{service.close();}
    }
    @Test void workerTimeoutIsInterrupted() throws Exception {
        var repo=repository();var service=new JobService(repo,(j,e)->{throw new TimeoutException();},1,1);
        try {var job=service.submit("timeout-key-12345","宝玉","lookup").job();await(repo,job.id(),"INTERRUPTED");}
        finally{service.close();}
    }
}
