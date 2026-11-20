// Example Spring Boot adapter. Adapt DTOs, auth, timeout and error mapping to the team's codebase.
package com.example.integration;

import org.springframework.beans.factory.annotation.Value;
import java.util.Map;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.util.LinkedMultiValueMap;
import org.springframework.util.MultiValueMap;
import org.springframework.web.client.RestClient;
import org.springframework.web.multipart.MultipartFile;

@Component
public class DataAiClient {
    private final RestClient client;

    public DataAiClient(
        RestClient.Builder builder,
        @Value("${services.data-ai.base-url}") String baseUrl,
        @Value("${services.data-ai.internal-token}") String token
    ) {
        this.client = builder.baseUrl(baseUrl)
            .defaultHeader("X-Internal-Service-Token", token).build();
    }

    public String upload(String caseId, MultipartFile file) throws Exception {
        MultiValueMap<String, Object> body = new LinkedMultiValueMap<>();
        body.add("file", new org.springframework.core.io.ByteArrayResource(file.getBytes()) {
            @Override public String getFilename() { return file.getOriginalFilename(); }
        });
        return client.post().uri("/api/v1/cases/{caseId}/documents", caseId)
            .contentType(MediaType.MULTIPART_FORM_DATA).body(body)
            .retrieve().body(String.class);
    }
    // Call only after Spring Security has authenticated the staff user and checked
    // bank scope. Never accept actor/bank/role headers from browser input.
    public byte[] exportExcel(String bankId, String actorId, String roles, String caseId) {
        return client.get()
            .uri(uriBuilder -> {
                uriBuilder.path("/api/v1/admin/exports/excel");
                if (caseId != null && !caseId.isBlank()) uriBuilder.queryParam("case_id", caseId);
                return uriBuilder.build();
            })
            .header("X-Actor-Id", actorId)
            .header("X-Actor-Roles", roles)
            .header("X-Bank-Id", bankId)
            .retrieve().body(byte[].class);
    }


    public String createCustomer(Map<String, Object> customerPayload) {
        return client.post().uri("/api/v1/customers")
            .contentType(MediaType.APPLICATION_JSON).body(customerPayload)
            .retrieve().body(String.class);
    }

    public String createCustomerApplication(String customerId, Map<String, Object> applicationPayload, String actorId) {
        return client.post().uri("/api/v1/customers/{customerId}/applications", customerId)
            .header("X-Actor-Id", actorId)
            .contentType(MediaType.APPLICATION_JSON).body(applicationPayload)
            .retrieve().body(String.class);
    }

    public String syncStaff(Map<String, Object> staffPayload, String actorId) {
        return client.post().uri("/api/v1/internal/staff-sync")
            .header("X-Actor-Id", actorId)
            .contentType(MediaType.APPLICATION_JSON).body(staffPayload)
            .retrieve().body(String.class);
    }

    // Forward only approved form fields after consent/purpose validation in Backend.
    public String submitApplicantSnapshot(String caseId, Map<String, Object> snapshot, String actorId) {
        return client.post()
            .uri("/api/v1/cases/{caseId}/applicant-submissions", caseId)
            .header("X-Actor-Id", actorId)
            .contentType(MediaType.APPLICATION_JSON)
            .body(snapshot)
            .retrieve().body(String.class);
    }

}
