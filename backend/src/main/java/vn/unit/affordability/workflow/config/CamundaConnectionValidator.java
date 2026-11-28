package vn.unit.affordability.workflow.config;

import io.camunda.client.CamundaClient;
import io.camunda.client.api.response.Topology;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.CommandLineRunner;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

import java.time.Duration;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

@Component // Automatically detected and registered as a bean
@ConditionalOnProperty(name = "camunda.connection.validator.enabled", havingValue = "true", matchIfMissing = true)
public class CamundaConnectionValidator implements CommandLineRunner {

    private static final Logger log = LoggerFactory.getLogger(
            CamundaConnectionValidator.class);
    private static final String SEPARATOR = "=".repeat(58);

    private final CamundaClient client;
    private final ValidatorProperties properties;

    // Connection status for health
    // AtomicReference is used to ensure thread-safe updates and reads
    private final AtomicReference<Boolean> connected = new AtomicReference<>(
            false);
    private final AtomicReference<Topology> lastTopology = new AtomicReference<>(
            null);
    private final AtomicReference<String> lastError = new AtomicReference<>(
            null);
    private final AtomicReference<Integer> lastAttempts = new AtomicReference<>(
            0);

    public CamundaConnectionValidator(CamundaClient client, ValidatorProperties properties) {
        this.client = client;
        this.properties = properties;
    }

    @Override
    public void run(String... args) {
        log.info("\n{}\n- CHECK CONNECTION TO CAMUNDA ZEEBE GATEWAY\n{}",
                SEPARATOR, SEPARATOR);

        Exception lastException = null;

        int retryAttempts = properties.getRetryAttempts();
        for (int attempt = 1; attempt <= retryAttempts; attempt++) {
            try {
                log.info("Attempt {}/{} to connect to Camunda Zeebe Gateway...",
                        attempt, retryAttempts);

                // topology is camunda zeebe cluster information
                Topology topology = client.newTopologyRequest()
                        .send()
                        .get(Duration.ofSeconds(10).toMillis(),
                                TimeUnit.MILLISECONDS);

                log.info("""

                        [SUCCESS] Successfully connected to Camunda Zeebe Gateway

                        - Gateway Version : {}
                        - Cluster Size    : {}
                        - Partitions      : {}
                        - Replication     : {}

                        {}
                        """,
                        topology.getGatewayVersion(),
                        topology.getClusterSize(),
                        topology.getPartitionsCount(),
                        topology.getReplicationFactor(),
                        SEPARATOR);

                // Update connection status for health endpoint
                connected.set(true);
                lastTopology.set(topology);
                lastError.set(null);
                lastAttempts.set(attempt);

                return; // Connection successful

            } catch (Exception e) {
                lastException = e;
                log.warn("Attempt {}/{} failed: {}",
                        attempt, retryAttempts, e.getMessage());

                // Update connection status for health endpoint
                connected.set(false);
                lastTopology.set(null);
                lastError.set(e.getMessage());
                lastAttempts.set(attempt);

                if (attempt < retryAttempts) {
                    try {
                        Thread.sleep(properties.getRetryDelayMs());
                    } catch (InterruptedException ie) {
                        Thread.currentThread().interrupt();
                        log.error(
                                "Thread is interrupted while retrying Camunda connection", ie);
                        throw new IllegalStateException(
                                "Camunda connection interrupted: " + ie.getMessage(), ie);
                    }
                }
            }
        }

        log.error("""

                [ERROR] Cannot connect to Camunda Zeebe Gateway after {} attempts
                - Reason: {}
                {}
                [WARNING] Backend will continue starting without Camunda.
                {}
                """,
                retryAttempts,
                lastException != null ? lastException.getMessage() : "Unknown error",
                SEPARATOR,
                SEPARATOR);

    }

    /**
     * @return whether Camunda Zeebe Gateway is currently reachable.
     */
    public boolean isConnected() {
        return connected.get();
    }

    /**
     * @return the last known topology from Camunda Zeebe Gateway, or
     *         null if never connected.
     */
    public Topology getLastTopology() {
        return lastTopology.get();
    }

    /**
     * @return the last error message from Camunda connection attempts, or
     *         null if no error.
     */
    public String getLastError() {
        return lastError.get();
    }

    /**
     * @return the number of attempts made during the last connection check.
     */
    public int getLastAttempts() {
        return lastAttempts.get();
    }
}