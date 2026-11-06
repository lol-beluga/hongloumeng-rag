package io.github.lolbeluga.honglou;

import tools.jackson.databind.JsonNode;

public record Job(String id, String question, String mode, String status, int attempt,
                  JsonNode result, String error, long createdAt, long updatedAt) {}
