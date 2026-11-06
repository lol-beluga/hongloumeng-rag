package io.github.lolbeluga.honglou;

import java.util.Optional;

public interface JobResultCache {
    // Empty Optional means a miss; Entry(null) is a short-lived not-found marker.
    record Entry(Job job) {}
    Optional<Entry> read(String id);
    void write(String id, Job job);
}
