package io.github.lolbeluga.honglou;

import java.util.List;
import java.util.UUID;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.Semaphore;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import jakarta.annotation.PreDestroy;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

@Service
public class JobService {
    private final JobRepository jobs;
    private final WorkerRunner worker;
    private final ThreadPoolExecutor executor;
    private final Semaphore admission;
    public record Submission(Job job, boolean replayed) {}

    public JobService(JobRepository jobs, WorkerRunner worker,
                      @Value("${research.workers}") int workers,
                      @Value("${research.queue-capacity}") int queueCapacity) {
        if (workers < 1 || queueCapacity < 1) throw new IllegalArgumentException("Invalid worker limits");
        this.jobs = jobs; this.worker = worker;
        executor = new ThreadPoolExecutor(workers, workers, 0, TimeUnit.SECONDS,
            new ArrayBlockingQueue<>(queueCapacity), new ThreadPoolExecutor.AbortPolicy());
        admission = new Semaphore(workers + queueCapacity);
        jobs.interruptUnfinished();
    }
    public Job get(String id) {
        return jobs.find(id).orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "任务不存在"));
    }
    public List<Job> recent(int limit) { return jobs.recent(limit); }
    public Submission submit(String key, String question, String mode) {
        question = question.strip();
        var existing = jobs.byKey(key);
        if (existing.isPresent()) return replay(existing.get(), question, mode);
        reserve();
        Job job;
        try {
            job = jobs.insert(UUID.randomUUID().toString().replace("-", ""), key, question, mode);
        } catch (DuplicateKeyException duplicate) {
            admission.release();
            return replay(jobs.byKey(key).orElseThrow(), question, mode);
        } catch (RuntimeException failure) {
            admission.release(); throw failure;
        }
        dispatch(job, false);
        return new Submission(job, false);
    }
    private Submission replay(Job job, String question, String mode) {
        if (!job.question().equals(question) || !job.mode().equals(mode))
            throw new ResponseStatusException(HttpStatus.CONFLICT, "同一请求编号不能用于不同的问题或模式");
        return new Submission(job, true);
    }
    public Job retry(String id, boolean extendBudget) {
        Job old = get(id);
        reserve();
        Job next;
        try {
            if (!jobs.retry(old)) throw new ResponseStatusException(HttpStatus.CONFLICT, "任务正在运行或已经完成，不能重复执行");
            next = get(id);
        } catch (RuntimeException failure) {
            admission.release(); throw failure;
        }
        dispatch(next, extendBudget);
        return next;
    }
    private void reserve() {
        if (!admission.tryAcquire()) throw new ResponseStatusException(HttpStatus.TOO_MANY_REQUESTS, "等待中的任务较多，请稍后再试");
    }
    private void dispatch(Job job, boolean extendBudget) {
        try {
            executor.execute(() -> {
                try {
                    if (!jobs.claim(job.id(), job.attempt())) return;
                    var result = worker.run(job, extendBudget);
                    String status = result.path("status").asText().equals("completed") ? "COMPLETED" : "PAUSED";
                    jobs.finish(job.id(), job.attempt(), status, result, null);
                } catch (TimeoutException timeout) {
                    jobs.finish(job.id(), job.attempt(), "INTERRUPTED", null, "执行超时。可检查配置后从已保存的检查点重试。");
                } catch (InterruptedException interrupted) {
                    jobs.finish(job.id(), job.attempt(), "INTERRUPTED", null, "服务停止，任务未完成。");
                    Thread.currentThread().interrupt();
                } catch (Exception failure) {
                    jobs.finish(job.id(), job.attempt(), "FAILED", null, "执行失败，请检查 Python 环境、语料及服务端模型配置。");
                } finally { admission.release(); }
            });
        } catch (RuntimeException rejected) {
            admission.release();
            jobs.finish(job.id(), job.attempt(), "FAILED", null, "执行队列不可用，请稍后重试。");
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "执行队列暂不可用");
        }
    }
    @PreDestroy public void close() {
        executor.shutdownNow();
        try { executor.awaitTermination(10, TimeUnit.SECONDS); }
        catch (InterruptedException e) { Thread.currentThread().interrupt(); }
    }
}
