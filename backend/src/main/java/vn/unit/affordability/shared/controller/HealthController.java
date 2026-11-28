package vn.unit.affordability.shared.controller;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import io.camunda.client.api.response.Topology;
import vn.unit.affordability.workflow.config.CamundaConnectionValidator;

import java.util.LinkedHashMap;
import java.util.Map;

@RestController
@RequestMapping("/api/v1")
public class HealthController {

    private final CamundaConnectionValidator camundaConnectionValidator;

    public HealthController(CamundaConnectionValidator camundaConnectionValidator) {
        this.camundaConnectionValidator = camundaConnectionValidator;
    }

    @GetMapping("/health")
    public ResponseEntity<Map<String, String>> getHealth() {
        return ResponseEntity.ok(Map.of("status", "UP"));
    }

    @GetMapping("/health/camunda")
    public ResponseEntity<Map<String, Object>> getCamundaHealth() {
        Map<String, Object> result = new LinkedHashMap<>();
        boolean connected = camundaConnectionValidator.isConnected();
        result.put("connected", connected);
        result.put("attempts", camundaConnectionValidator.getLastAttempts());

        if (connected) {
            Topology topology = camundaConnectionValidator.getLastTopology();
            result.put("status", "UP");
            result.put("gatewayVersion", topology.getGatewayVersion());
            result.put("clusterSize", topology.getClusterSize());
            result.put("partitions", topology.getPartitionsCount());
            result.put("replicationFactor", topology.getReplicationFactor());
            result.put("error", null);
        } else {
            result.put("status", "DOWN");
            result.put("gatewayVersion", null);
            result.put("clusterSize", null);
            result.put("partitions", null);
            result.put("replicationFactor", null);
            result.put("error", camundaConnectionValidator.getLastError());
        }

        return ResponseEntity.ok(result);
    }
}
