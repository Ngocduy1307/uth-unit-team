package vn.unit.affordability.shared.controller;

import io.camunda.client.api.response.Topology;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import vn.unit.affordability.workflow.config.CamundaConnectionValidator;

import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

// Enable Mockito in JUnit 5 to automatically initialize `mock objects` (@Mock)
// and inject them into the `test class` (@InjectMocks).
@ExtendWith(MockitoExtension.class)
// Allow to define mock behavior (when(...)) without throwing an
// UnnecessaryStubbingException for unused stubs.
@MockitoSettings(strictness = Strictness.LENIENT)
class HealthControllerTest {

    @Mock
    private CamundaConnectionValidator camundaConnectionValidator;

    @Mock
    private Topology topology;

    @InjectMocks
    private HealthController healthController;

    private MockMvc mockMvc;

    @BeforeEach
    void setUp() {
        // Initialize ultra-lightweight HTTP environment
        mockMvc = MockMvcBuilders.standaloneSetup(healthController).build();
    }

    @Test
    @DisplayName("GET /api/v1/health should return 200 OK and status UP")
    void healthCheckShouldReturnStatusUp() throws Exception {
        mockMvc.perform(get("/api/v1/health")
                .accept(MediaType.APPLICATION_JSON))
                .andExpect(status().isOk())
                .andExpect(content().contentType(MediaType.APPLICATION_JSON))
                .andExpect(jsonPath("$.status").value("UP"));
    }

    @Test
    @DisplayName("GET /api/v1/health/camunda " +
            "should return connected status when Camunda is reachable")
    void camundaHealthShouldReturnConnectedWhenReachable() throws Exception {
        // Arrange
        when(camundaConnectionValidator.isConnected()).thenReturn(true);
        when(camundaConnectionValidator.getLastAttempts()).thenReturn(1);

        when(camundaConnectionValidator.getLastTopology()).thenReturn(topology);
        when(topology.getGatewayVersion()).thenReturn("8.9.0");
        when(topology.getClusterSize()).thenReturn(1);
        when(topology.getPartitionsCount()).thenReturn(1);
        when(topology.getReplicationFactor()).thenReturn(1);
        when(camundaConnectionValidator.getLastError()).thenReturn(null);

        // Assert
        mockMvc.perform(get("/api/v1/health/camunda")
                .accept(MediaType.APPLICATION_JSON))
                .andExpect(status().isOk()) // HTTP 200 OK
                .andExpect(content().contentType(MediaType.APPLICATION_JSON))
                .andExpect(jsonPath("$.connected").value(true))
                .andExpect(jsonPath("$.attempts").value(1))
                .andExpect(jsonPath("$.status").value("UP"))
                .andExpect(jsonPath("$.gatewayVersion").value("8.9.0"))
                .andExpect(jsonPath("$.clusterSize").value(1))
                .andExpect(jsonPath("$.partitions").value(1))
                .andExpect(jsonPath("$.replicationFactor").value(1))
                .andExpect(jsonPath("$.error").isEmpty());
    }

    @Test
    @DisplayName("GET /api/v1/health/camunda " +
            "should return disconnected status when Camunda is unreachable")
    void camundaHealthShouldReturnDisconnectedWhenUnreachable() throws Exception {
        // Arrange
        when(camundaConnectionValidator.isConnected()).thenReturn(false);
        when(camundaConnectionValidator.getLastAttempts()).thenReturn(5);
        when(camundaConnectionValidator.getLastTopology()).thenReturn(null);
        when(camundaConnectionValidator.getLastError()).thenReturn("Gateway unreachable");

        // Assert
        mockMvc.perform(get("/api/v1/health/camunda")
                .accept(MediaType.APPLICATION_JSON))
                .andExpect(status().isOk()) // HTTP 200 OK
                .andExpect(content().contentType(MediaType.APPLICATION_JSON))
                .andExpect(jsonPath("$.connected").value(false))
                .andExpect(jsonPath("$.attempts").value(5))
                .andExpect(jsonPath("$.status").value("DOWN"))
                .andExpect(jsonPath("$.gatewayVersion").isEmpty())
                .andExpect(jsonPath("$.error").value("Gateway unreachable"));
    }
}
