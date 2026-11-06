package io.github.lolbeluga.honglou;

import tools.jackson.databind.JsonNode;

public record Job(String id, String question, String mode, String status, int attempt,
                  JsonNode result, String error, long createdAt, long updatedAt) {
    public Job {
        if (result != null && result.isNull()) result = null;
    }
}
