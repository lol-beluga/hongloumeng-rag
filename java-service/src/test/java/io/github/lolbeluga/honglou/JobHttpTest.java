package io.github.lolbeluga.honglou;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.context.annotation.Primary;
import tools.jackson.databind.json.JsonMapper;
import static org.junit.jupiter.api.Assertions.*;

@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT,
    properties = "spring.datasource.url=jdbc:h2:mem:http;DB_CLOSE_DELAY=-1")
@Import(JobHttpTest.Workers.class)
class JobHttpTest {
    @LocalServerPort int port;
    final HttpClient client = HttpClient.newHttpClient();
    final JsonMapper json = JsonMapper.builder().build();

    @TestConfiguration
    static class Workers {
        @Bean @Primary WorkerRunner testWorker() {
            return (job, extended) -> JsonMapper.builder().build().readTree(
                "{\"run_id\":\"" + job.id() + "\",\"status\":\"completed\",\"sources\":[]}");
        }
    }
    HttpResponse<String> post(String key, String body) throws Exception {
        return client.send(HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + port + "/api/jobs"))
            .header("Content-Type", "application/json").header("Idempotency-Key", key)
            .POST(HttpRequest.BodyPublishers.ofString(body)).build(), HttpResponse.BodyHandlers.ofString());
    }
    @Test void acceptedJobHasLocationReplayAndQueryableResult() throws Exception {
        String key = UUID.randomUUID().toString();
        String body = "{\"question\":\"黛玉葬花\",\"mode\":\"lookup\"}";
        var first = post(key, body);
        assertEquals(202, first.statusCode(), first.body());
        var id = json.readTree(first.body()).path("id").asText();
        assertEquals("/api/jobs/" + id, first.headers().firstValue("Location").orElseThrow());
        var replay = post(key, body);
        assertEquals(200, replay.statusCode());
        assertEquals(id, json.readTree(replay.body()).path("id").asText());
        assertEquals("true", replay.headers().firstValue("Idempotency-Replayed").orElseThrow());
        assertEquals(409, post(key, "{\"question\":\"宝钗\",\"mode\":\"lookup\"}").statusCode());
        String status = "";
        for (int i = 0; i < 50; i++) {
            var read = client.send(HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + port + "/api/jobs/" + id))
                .GET().build(), HttpResponse.BodyHandlers.ofString());
            assertEquals(200, read.statusCode());
            var node = json.readTree(read.body());
            status = node.path("status").asText();
            if (status.equals("COMPLETED")) {
                assertEquals(id, node.path("result").path("run_id").asText());
                break;
            }
            Thread.sleep(20);
        }
        assertEquals("COMPLETED", status);
    }
    @Test void rejectsBadInputBeforeCreatingJob() throws Exception {
        assertEquals(400, post("short", "{\"question\":\"宝玉\",\"mode\":\"lookup\"}").statusCode());
        assertEquals(400, post(UUID.randomUUID().toString(), "{\"question\":\"  \",\"mode\":\"lookup\"}").statusCode());
        assertEquals(400, post(UUID.randomUUID().toString(), "{\"question\":\"宝玉\",\"mode\":\"shell\"}").statusCode());
    }
}
