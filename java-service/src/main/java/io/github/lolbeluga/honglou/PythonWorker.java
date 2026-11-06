package io.github.lolbeluga.honglou;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Map;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

@Component
public class PythonWorker implements WorkerRunner {
    private final String python;
    private final Path project;
    private final int timeout;
    private final JsonMapper json = JsonMapper.builder().build();

    public PythonWorker(@Value("${research.python}") String python,
                        @Value("${research.project-dir}") String project,
                        @Value("${research.timeout-seconds}") int timeout) {
        this.python = python; this.project = Path.of(project).toAbsolutePath().normalize();
        this.timeout = timeout;
    }
    public JsonNode run(Job job, boolean extendBudget) throws Exception {
        Path output = Files.createTempFile("honglou-worker-", ".json");
        Process process = null;
        try {
            ProcessBuilder builder = new ProcessBuilder(python, project.resolve("java_worker.py").toString());
            builder.directory(project.toFile());
            builder.environment().put("PYTHONIOENCODING", "utf-8");
            builder.redirectOutput(output.toFile());
            builder.redirectError(ProcessBuilder.Redirect.DISCARD);
            process = builder.start();
            try (var input = process.getOutputStream()) {
                input.write(json.writeValueAsString(Map.of("id", job.id(), "question", job.question(),
                    "mode", job.mode(), "extend_budget", extendBudget)).getBytes(StandardCharsets.UTF_8));
            }
            if (!process.waitFor(timeout, TimeUnit.SECONDS)) throw new TimeoutException("worker deadline");
            if (process.exitValue() != 0) throw new IllegalStateException("Python worker failed");
            if (Files.size(output) > 2_000_000) throw new IllegalStateException("worker response too large");
            JsonNode result = json.readTree(Files.readString(output, StandardCharsets.UTF_8));
            if (!job.id().equals(result.path("run_id").asText())) throw new IllegalStateException("worker ID mismatch");
            String status = result.path("status").asText();
            if (!status.equals("completed") && !status.equals("paused")) throw new IllegalStateException("invalid worker status");
            return result;
        } finally {
            if (process != null && process.isAlive()) {
                process.descendants().forEach(ProcessHandle::destroyForcibly);
                process.destroyForcibly();
                process.waitFor(5, TimeUnit.SECONDS);
            }
            Files.deleteIfExists(output);
        }
    }
}
