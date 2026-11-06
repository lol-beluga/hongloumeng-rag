package io.github.lolbeluga.honglou;

import java.util.Optional;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

@Component
@ConditionalOnProperty(name="research.cache.enabled", havingValue="false", matchIfMissing=true)
public class DisabledJobCache implements JobResultCache {
    public Optional<Entry> read(String id) { return Optional.empty(); }
    public void write(String id, Job job) {}
}
