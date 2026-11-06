package io.github.lolbeluga.honglou;

import java.net.URI;
import java.util.List;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;

@RestController
@RequestMapping("/api/jobs")
public class JobController {
    private final JobService service;
    private final JobQueryService queries;
    public JobController(JobService service, JobQueryService queries) {
        this.service = service;
        this.queries = queries;
    }
    public record CreateRequest(@NotBlank @Size(max=2000) String question,
                                @NotBlank @Pattern(regexp="lookup|research") String mode) {}
    public record RetryRequest(boolean extendBudget) {}
    @PostMapping
    public ResponseEntity<Job> submit(@RequestHeader("Idempotency-Key") String key,
                                      @Valid @RequestBody CreateRequest request) {
        if (!key.matches("[A-Za-z0-9_-]{16,128}"))
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "请求编号须为16至128位字母、数字、下划线或连字符");
        var result = service.submit(key, request.question(), request.mode());
        return ResponseEntity.status(result.replayed() ? 200 : 202)
            .location(URI.create("/api/jobs/" + result.job().id()))
            .header("Idempotency-Replayed", Boolean.toString(result.replayed())).body(result.job());
    }
    @GetMapping public List<Job> recent(@RequestParam(defaultValue="20") int limit) {
        if (limit < 1 || limit > 100) throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "limit须为1至100");
        return service.recent(limit);
    }
    @GetMapping("/{id}") public Job get(@PathVariable String id) { return queries.get(id); }
    @PostMapping("/{id}/retry") public ResponseEntity<Job> retry(@PathVariable String id,
                         @RequestBody(required=false) RetryRequest request) {
        return ResponseEntity.accepted().body(service.retry(id, request != null && request.extendBudget()));
    }
}
