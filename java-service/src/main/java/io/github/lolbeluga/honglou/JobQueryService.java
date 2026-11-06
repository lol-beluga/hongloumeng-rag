package io.github.lolbeluga.honglou;

import java.util.concurrent.locks.ReentrantLock;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

@Service
public class JobQueryService {
    private final JobRepository jobs;
    private final JobResultCache cache;
    private final ReentrantLock[] locks = new ReentrantLock[256];

    public JobQueryService(JobRepository jobs, JobResultCache cache) {
        this.jobs = jobs;
        this.cache = cache;
        for (int i = 0; i < locks.length; i++) locks[i] = new ReentrantLock();
    }
    public Job get(String id) {
        if (!id.matches("[0-9a-f]{32}")) return require(null);
        var cached = cache.read(id);
        if (cached.isPresent()) return require(cached.get().job());
        // A bounded set of locks avoids retaining one lock for every queried ID.
        var lock = locks[Math.floorMod(id.hashCode(), locks.length)];
        lock.lock();
        try {
            cached = cache.read(id);
            if (cached.isPresent()) return require(cached.get().job());
            Job job = jobs.find(id).orElse(null);
            if (job == null || job.status().equals("COMPLETED")) cache.write(id, job);
            return require(job);
        } finally { lock.unlock(); }
    }
    private Job require(Job job) {
        if (job == null) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "任务不存在");
        return job;
    }
}
