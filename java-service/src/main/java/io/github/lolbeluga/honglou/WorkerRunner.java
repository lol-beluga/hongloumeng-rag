package io.github.lolbeluga.honglou;

import tools.jackson.databind.JsonNode;

public interface WorkerRunner {
    JsonNode run(Job job, boolean extendBudget) throws Exception;
}
