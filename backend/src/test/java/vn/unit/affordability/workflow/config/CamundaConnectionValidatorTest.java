package vn.unit.affordability.workflow.config;

import io.camunda.client.CamundaClient;
import io.camunda.client.api.CamundaFuture;
import io.camunda.client.api.command.TopologyRequestStep1;
import io.camunda.client.api.response.Topology;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import java.util.concurrent.ExecutionException;
import java.util.concurrent.TimeoutException;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
class CamundaConnectionValidatorTest {

    @Mock
    private CamundaClient client;

    @Mock
    private TopologyRequestStep1 topologyRequest;

    @Mock
    private Topology topology;

    @Mock
    private CamundaFuture<Topology> camundaFuture;

    @Mock
    private ValidatorProperties properties;

    @InjectMocks
    private CamundaConnectionValidator camundaConnectionValidator;

    // Happy Path Tests

    @Test
    @DisplayName("Should not throw an exception when " +
            "Camunda connection succeeds on first attempt")
    void testConnectionSuccess() throws Exception {
        // Arrange
        when(properties.getRetryAttempts()).thenReturn(1);
        when(properties.getRetryDelayMs()).thenReturn(100L); // 100ms
        when(topology.getGatewayVersion()).thenReturn("8.9.0");
        when(topology.getClusterSize()).thenReturn(1);
        when(topology.getPartitionsCount()).thenReturn(1);
        when(topology.getReplicationFactor()).thenReturn(1);

        // CamundaClient return topologyRequestStep1
        when(client.newTopologyRequest()).thenReturn(topologyRequest);
        // topologyRequestStep1 return camundaFuture
        when(topologyRequest.send()).thenReturn(camundaFuture);
        // camundaFuture return topology
        when(camundaFuture.get(anyLong(), any())).thenReturn(topology);

        // Assert
        assertDoesNotThrow(() -> camundaConnectionValidator.run());
        verify(client, times(1)).newTopologyRequest();
        assertTrue(camundaConnectionValidator.isConnected());
    }

    @Test
    @DisplayName("Should return connected status with gateway version when " +
            "Camunda connection is successful")
    void testGatewayVersionDisplayed() throws Exception {
        when(properties.getRetryAttempts()).thenReturn(1);
        when(properties.getRetryDelayMs()).thenReturn(100L);
        when(topology.getGatewayVersion()).thenReturn("8.9.0");
        when(topology.getClusterSize()).thenReturn(1);
        when(topology.getPartitionsCount()).thenReturn(1);
        when(topology.getReplicationFactor()).thenReturn(1);

        when(client.newTopologyRequest()).thenReturn(topologyRequest);
        when(topologyRequest.send()).thenReturn(camundaFuture);
        when(camundaFuture.get(anyLong(), any())).thenReturn(topology);

        assertDoesNotThrow(() -> camundaConnectionValidator.run());
        assertTrue(camundaConnectionValidator.isConnected());
        assertEquals("8.9.0", camundaConnectionValidator.getLastTopology().getGatewayVersion());
    }

    @Test
    @DisplayName("Should return cluster size from topology")
    void testClusterSizeFromValues() throws Exception {
        when(properties.getRetryAttempts()).thenReturn(1);
        when(properties.getRetryDelayMs()).thenReturn(100L);
        when(topology.getGatewayVersion()).thenReturn("8.9.0");
        when(topology.getClusterSize()).thenReturn(1);
        when(topology.getPartitionsCount()).thenReturn(1);
        when(topology.getReplicationFactor()).thenReturn(1);

        when(client.newTopologyRequest()).thenReturn(topologyRequest);
        when(topologyRequest.send()).thenReturn(camundaFuture);
        when(camundaFuture.get(anyLong(), any())).thenReturn(topology);

        assertDoesNotThrow(() -> camundaConnectionValidator.run());
        assertTrue(camundaConnectionValidator.isConnected());
        assertEquals(1, camundaConnectionValidator.getLastTopology()
                .getClusterSize());
    }

    @Test
    @DisplayName("Should return partition count from topology")
    void testPartitionCountFromValues() throws Exception {
        when(properties.getRetryAttempts()).thenReturn(1);
        when(properties.getRetryDelayMs()).thenReturn(100L);
        when(topology.getGatewayVersion()).thenReturn("8.9.0");
        when(topology.getClusterSize()).thenReturn(1);
        when(topology.getPartitionsCount()).thenReturn(1);
        when(topology.getReplicationFactor()).thenReturn(1);

        when(client.newTopologyRequest()).thenReturn(topologyRequest);
        when(topologyRequest.send()).thenReturn(camundaFuture);
        when(camundaFuture.get(anyLong(), any())).thenReturn(topology);

        assertDoesNotThrow(() -> camundaConnectionValidator.run());
        assertTrue(camundaConnectionValidator.isConnected());
        assertEquals(1, camundaConnectionValidator.getLastTopology().getPartitionsCount());
    }

    @Test
    @DisplayName("Should return replication factor from topology")
    void testReplicationFactorFromValues() throws Exception {
        when(properties.getRetryAttempts()).thenReturn(1);
        when(properties.getRetryDelayMs()).thenReturn(100L);
        when(topology.getGatewayVersion()).thenReturn("8.9.0");
        when(topology.getClusterSize()).thenReturn(1);
        when(topology.getPartitionsCount()).thenReturn(1);
        when(topology.getReplicationFactor()).thenReturn(1);

        when(client.newTopologyRequest()).thenReturn(topologyRequest);
        when(topologyRequest.send()).thenReturn(camundaFuture);
        when(camundaFuture.get(anyLong(), any())).thenReturn(topology);

        assertDoesNotThrow(() -> camundaConnectionValidator.run());
        assertTrue(camundaConnectionValidator.isConnected());
        assertEquals(1, camundaConnectionValidator.getLastTopology()
                .getReplicationFactor());
    }

    // Fault Tolerance Tests

    @Test
    @DisplayName("Should not throw an exception " +
            "when Camunda connection fails, backend continues starting")
    void testConnectionFailure() {
        // Arrange
        when(properties.getRetryAttempts()).thenReturn(1);
        when(properties.getRetryDelayMs()).thenReturn(100L);

        when(client.newTopologyRequest()).thenThrow(
                new RuntimeException("Gateway unreachable"));

        // Assert
        assertDoesNotThrow(() -> camundaConnectionValidator.run());
        assertFalse(camundaConnectionValidator.isConnected());
        assertNotNull(camundaConnectionValidator.getLastError());
    }

    // Exception Handling Tests

    @Test
    @DisplayName("Should handle timeout applied to topology request without " +
            "throwing an exception")
    void testTimeoutApplied() throws Exception {
        when(properties.getRetryAttempts()).thenReturn(1);
        when(properties.getRetryDelayMs()).thenReturn(100L);

        when(client.newTopologyRequest()).thenReturn(topologyRequest);
        // anyLong() and any() is placeholder
        when(camundaFuture.get(anyLong(), any())).thenThrow(
                new TimeoutException("Gateway timeout"));
        when(topologyRequest.send()).thenReturn(camundaFuture);

        assertDoesNotThrow(() -> camundaConnectionValidator.run());
        assertFalse(camundaConnectionValidator.isConnected());
        assertNotNull(camundaConnectionValidator.getLastError());
    }

    @Test
    @DisplayName("Should handle timeout exception wrapped without " +
            "throwing an exception")
    void testTimeoutExceptionWrapped() throws Exception {
        when(properties.getRetryAttempts()).thenReturn(1);
        when(properties.getRetryDelayMs()).thenReturn(100L);

        when(client.newTopologyRequest()).thenReturn(topologyRequest);
        when(camundaFuture.get(anyLong(), any())).thenThrow(
                new TimeoutException("Zeebe Gateway timeout"));
        when(topologyRequest.send()).thenReturn(camundaFuture);

        assertDoesNotThrow(() -> camundaConnectionValidator.run());
        assertFalse(camundaConnectionValidator.isConnected());
        assertNotNull(camundaConnectionValidator.getLastError());
    }

    @Test
    @DisplayName("Should handle execution exception wrapped without " +
            "throwing an exception")
    void testExecutionExceptionWrapped() throws Exception {
        when(properties.getRetryAttempts()).thenReturn(1);
        when(properties.getRetryDelayMs()).thenReturn(100L);

        when(client.newTopologyRequest()).thenReturn(topologyRequest);
        when(camundaFuture.get(anyLong(), any())).thenThrow(
                new ExecutionException(new RuntimeException("Internal Zeebe error")));
        when(topologyRequest.send()).thenReturn(camundaFuture);

        assertDoesNotThrow(() -> camundaConnectionValidator.run());
        assertFalse(camundaConnectionValidator.isConnected());
        assertNotNull(camundaConnectionValidator.getLastError());
    }

    @Test
    @DisplayName("Should handle interrupted exception without " +
            "throwing an exception")
    void testInterruptedExceptionWrapped() throws Exception {
        when(properties.getRetryAttempts()).thenReturn(1);
        when(properties.getRetryDelayMs()).thenReturn(100L);

        when(client.newTopologyRequest()).thenReturn(topologyRequest);
        when(camundaFuture.get(anyLong(), any())).thenThrow(
                new InterruptedException("Thread interrupted"));
        when(topologyRequest.send()).thenReturn(camundaFuture);

        assertDoesNotThrow(() -> camundaConnectionValidator.run());
        assertFalse(camundaConnectionValidator.isConnected());
        assertNotNull(camundaConnectionValidator.getLastError());
    }

    // Retry Logic Tests

    @Test
    @DisplayName("Should retry multiple times before giving up")
    void testRetryMultipleAttempts() throws Exception {
        when(properties.getRetryAttempts()).thenReturn(3);
        when(properties.getRetryDelayMs()).thenReturn(100L);

        when(client.newTopologyRequest()).thenReturn(topologyRequest);
        when(camundaFuture.get(anyLong(), any())).thenThrow(
                new TimeoutException("Gateway timeout"));
        when(topologyRequest.send()).thenReturn(camundaFuture);

        assertDoesNotThrow(() -> camundaConnectionValidator.run());
        assertFalse(camundaConnectionValidator.isConnected());
        assertEquals(3, camundaConnectionValidator.getLastAttempts());
    }
}