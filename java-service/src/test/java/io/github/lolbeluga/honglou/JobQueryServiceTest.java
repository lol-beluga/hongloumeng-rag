package io.github.lolbeluga.honglou;

import java.util.Optional;
import java.util.concurrent.*;
import org.junit.jupiter.api.Test;
import org.springframework.web.server.ResponseStatusException;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

class JobQueryServiceTest {
    final String id = "a".repeat(32);
    Job job(String status) { return new Job(id,"黛玉","lookup",status,1,null,null,1,2); }
    static class MemoryCache implements JobResultCache {
        final ConcurrentHashMap<String, Entry> entries = new ConcurrentHashMap<>();
        public Optional<Entry> read(String id) { return Optional.ofNullable(entries.get(id)); }
        public void write(String id, Job job) { entries.put(id, new Entry(job)); }
    }
    @Test void completedResultIsReusedAndColdConcurrentReadsAreCoalesced() throws Exception {
        var repo = mock(JobRepository.class);
        when(repo.find(id)).thenAnswer(invocation -> { Thread.sleep(50); return Optional.of(job("COMPLETED")); });
        var queries = new JobQueryService(repo, new MemoryCache());
        try (var clients = Executors.newFixedThreadPool(8)) {
            var tasks = java.util.stream.IntStream.range(0,8)
                .mapToObj(i -> (Callable<Job>) () -> queries.get(id)).toList();
            for (var result : clients.invokeAll(tasks)) assertEquals("COMPLETED", result.get().status());
        }
        verify(repo, times(1)).find(id);
    }
    @Test void mutableStatusIsNeverCached() {
        var repo = mock(JobRepository.class);
        when(repo.find(id)).thenReturn(Optional.of(job("PAUSED")), Optional.of(job("RUNNING")), Optional.of(job("COMPLETED")));
        var queries = new JobQueryService(repo, new MemoryCache());
        assertEquals("PAUSED", queries.get(id).status());
        assertEquals("RUNNING", queries.get(id).status());
        assertEquals("COMPLETED", queries.get(id).status());
        assertEquals("COMPLETED", queries.get(id).status());
        verify(repo, times(3)).find(id);
    }
    @Test void missingJobIsNegativelyCachedAndMalformedIdsNeverReachDatabase() {
        var repo = mock(JobRepository.class);
        when(repo.find(id)).thenReturn(Optional.empty());
        var queries = new JobQueryService(repo, new MemoryCache());
        for (int i=0;i<2;i++) assertEquals(404, assertThrows(ResponseStatusException.class, () -> queries.get(id)).getStatusCode().value());
        assertThrows(ResponseStatusException.class, () -> queries.get("invalid"));
        verify(repo, times(1)).find(id);
        verifyNoMoreInteractions(repo);
    }
}
