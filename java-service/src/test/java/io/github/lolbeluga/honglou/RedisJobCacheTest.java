package io.github.lolbeluga.honglou;

import java.time.Duration;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.data.redis.RedisConnectionFailureException;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class RedisJobCacheTest {
    @SuppressWarnings("unchecked")
    ValueOperations<String,String> values() { return mock(ValueOperations.class); }
    @Test void redisFailureFallsBackAndSkipsFurtherCallsDuringCooldown() {
        var template = mock(StringRedisTemplate.class);
        var values = values(); when(template.opsForValue()).thenReturn(values);
        when(values.get(anyString())).thenThrow(new RedisConnectionFailureException("offline"));
        var cache = new RedisJobCache(template,"test:",900,120,30);
        assertTrue(cache.read("a").isEmpty());
        assertTrue(cache.read("b").isEmpty());
        cache.write("c",null);
        verify(values, times(1)).get(anyString());
        verify(values, never()).set(anyString(),anyString(),any(Duration.class));
    }
    @Test void completedEntryRoundTripsWithBoundedTtlAndRunningEntryIsIgnored() {
        var template = mock(StringRedisTemplate.class);
        var values = values(); when(template.opsForValue()).thenReturn(values);
        var cache = new RedisJobCache(template,"test:",900,120,30);
        var job = new Job("a","黛玉🌸","research","COMPLETED",1,null,null,1,2);
        cache.write("a",job);
        var payload = ArgumentCaptor.forClass(String.class);
        var ttl = ArgumentCaptor.forClass(Duration.class);
        verify(values).set(eq("test:a"),payload.capture(),ttl.capture());
        assertTrue(ttl.getValue().toSeconds() >= 900 && ttl.getValue().toSeconds() <= 1020);
        when(values.get("test:a")).thenReturn(payload.getValue());
        assertEquals(job,cache.read("a").orElseThrow().job());
        cache.write("b",new Job("b","问题","lookup","RUNNING",1,null,null,1,2));
        verify(values, times(1)).set(anyString(),anyString(),any(Duration.class));
    }
    @Test void corruptPayloadAndMismatchedIdsAreCacheMisses() {
        var template = mock(StringRedisTemplate.class);
        var values = values(); when(template.opsForValue()).thenReturn(values);
        when(values.get("test:a")).thenReturn("not json");
        assertTrue(new RedisJobCache(template,"test:",900,0,30).read("a").isEmpty());
        when(values.get("test:a")).thenReturn("{\"job\":{\"id\":\"b\",\"question\":\"q\",\"mode\":\"lookup\",\"status\":\"COMPLETED\",\"attempt\":1,\"result\":null,\"error\":null,\"createdAt\":1,\"updatedAt\":2}}");
        assertTrue(new RedisJobCache(template,"test:",900,0,30).read("a").isEmpty());
        verify(template).delete("test:a");
    }
}
