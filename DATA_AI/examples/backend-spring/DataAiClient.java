package com.example.integration;

// Example Spring Boot adapter. Adapt DTOs, auth, timeout and error mapping to the team's codebase.
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.beans.factory.annotation.Value;
import java.io.ByteArrayOutputStream;
import java.net.http.HttpClient;
import java.time.Duration;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.HexFormat;
import java.util.Map;
import java.util.function.Supplier;
import org.springframework.http.MediaType;
import org.springframework.http.client.JdkClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;
import org.springframework.web.multipart.MultipartFile;

@Component
public class DataAiClient {
    private final RestClient client;
    private final String circuitKey;
    private final ObjectMapper objectMapper;

    public DataAiClient(
        RestClient.Builder builder,
        ObjectMapper objectMapper,
        @Value("${services.data-ai.base-url}") String baseUrl,
        @Value("${services.data-ai.internal-token}") String token,
        @Value("${services.data-ai.assertion-key-id}") String assertionKeyId,
        @Value("${services.data-ai.assertion-secret}") String assertionSecret,
        @Value("${services.data-ai.assertion-issuer:spring-boot-backend}") String assertionIssuer,
        @Value("${services.data-ai.assertion-audience:data-ai}") String assertionAudience,
        @Value("${services.data-ai.connect-timeout-seconds:3}") int connectTimeoutSeconds,
        @Value("${services.data-ai.read-timeout-seconds:90}") int readTimeoutSeconds
    ) {
        if (connectTimeoutSeconds < 1 || readTimeoutSeconds < 1) {
            throw new IllegalArgumentException("DATA-AI timeouts must be positive");
        }
        this.circuitKey = baseUrl;
        this.objectMapper = objectMapper;
        HttpClient httpClient = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(connectTimeoutSeconds)).build();
        JdkClientHttpRequestFactory requestFactory = new JdkClientHttpRequestFactory(httpClient);
        requestFactory.setReadTimeout(Duration.ofSeconds(readTimeoutSeconds));
        this.client = builder.baseUrl(baseUrl)
            .requestFactory(requestFactory)
            .defaultHeader("X-Internal-Service-Token", token)
            .requestInterceptor(new DataAiSignedAssertionInterceptor(assertionKeyId, assertionSecret, assertionIssuer, assertionAudience))
            .build();
    }

    private <T> T resilient(Supplier<T> request) {
        return DataAiResilience.execute(circuitKey, request);
    }

    private static String requireIdempotencyKey(String key) {
        if (key == null || !key.matches("[A-Za-z0-9][A-Za-z0-9._:-]{7,127}")) {
            throw new IllegalArgumentException("A stable 8-128 character Idempotency-Key is required");
        }
        return key;
    }

    private byte[] jsonBytes(Object value) {
        try {
            return objectMapper.writeValueAsBytes(value);
        } catch (JsonProcessingException ex) {
            throw new IllegalArgumentException("Cannot serialize DATA-AI request payload", ex);
        }
    }

    /** Persist this logical command key in Backend before dispatch; reuse it on every retry. */
    public String upload(String idempotencyKey, String caseId, MultipartFile file,
                         String actorId, String roles, String bankCode) throws Exception {
        String key = requireIdempotencyKey(idempotencyKey);
        byte[] fileBytes = file.getBytes();
        String boundary = multipartBoundary(key, fileBytes);
        byte[] multipartBody = multipartBody(boundary, file, fileBytes);
        MediaType multipartType = MediaType.parseMediaType("multipart/form-data; boundary=" + boundary);
        return resilient(() -> client.post().uri("/api/v1/cases/{caseId}/documents", caseId)
            .header("Idempotency-Key", key)
            .header("X-Actor-Id", actorId)
            .header("X-Actor-Roles", roles)
            .header("X-Bank-Id", bankCode)
            .contentType(multipartType).body(multipartBody)
            .retrieve().body(String.class));
    }

    // GET export currently creates an ExportJob and audit records on DATA-AI;
    // deliberately do not auto-retry it until the API is changed to a safe POST command.
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

    public String createCustomer(String idempotencyKey, Map<String, Object> customerPayload,
                                 String actorId, String roles, String bankCode) {
        String key = requireIdempotencyKey(idempotencyKey);
        byte[] body = jsonBytes(customerPayload);
        return resilient(() -> client.post().uri("/api/v1/customers")
            .header("Idempotency-Key", key)
            .header("X-Actor-Id", actorId)
            .header("X-Actor-Roles", roles)
            .header("X-Bank-Id", bankCode)
            .contentType(MediaType.APPLICATION_JSON).body(body)
            .retrieve().body(String.class));
    }

    public String createCustomerApplication(String idempotencyKey, String customerId,
                                            Map<String, Object> applicationPayload,
                                            String actorId, String roles, String bankCode) {
        String key = requireIdempotencyKey(idempotencyKey);
        byte[] body = jsonBytes(applicationPayload);
        return resilient(() -> client.post().uri("/api/v1/customers/{customerId}/applications", customerId)
            .header("Idempotency-Key", key)
            .header("X-Actor-Id", actorId)
            .header("X-Actor-Roles", roles)
            .header("X-Bank-Id", bankCode)
            .contentType(MediaType.APPLICATION_JSON).body(body)
            .retrieve().body(String.class));
    }

    public String syncStaff(String idempotencyKey, Map<String, Object> staffPayload,
                            String actorId, String roles, String bankCode) {
        String key = requireIdempotencyKey(idempotencyKey);
        byte[] body = jsonBytes(staffPayload);
        return resilient(() -> client.post().uri("/api/v1/internal/staff-sync")
            .header("Idempotency-Key", key)
            .header("X-Actor-Id", actorId)
            .header("X-Actor-Roles", roles)
            .header("X-Bank-Id", bankCode)
            .contentType(MediaType.APPLICATION_JSON).body(body)
            .retrieve().body(String.class));
    }

    // Forward only approved form fields after consent/purpose validation in Backend.
    public String submitApplicantSnapshot(String idempotencyKey, String caseId,
                                          Map<String, Object> snapshot,
                                          String actorId, String roles, String bankCode) {
        String key = requireIdempotencyKey(idempotencyKey);
        byte[] body = jsonBytes(snapshot);
        return resilient(() -> client.post()
            .uri("/api/v1/cases/{caseId}/applicant-submissions", caseId)
            .header("Idempotency-Key", key)
            .header("X-Actor-Id", actorId)
            .header("X-Actor-Roles", roles)
            .header("X-Bank-Id", bankCode)
            .contentType(MediaType.APPLICATION_JSON)
            .body(body)
            .retrieve().body(String.class));
    }

    private static byte[] multipartBody(String boundary, MultipartFile file, byte[] fileBytes) throws Exception {
        String filename = file.getOriginalFilename() == null ? "upload.bin" : file.getOriginalFilename();
        filename = filename.replaceAll("[\\r\\n\\\"\\\\]", "_");
        String mime = file.getContentType() == null ? "application/octet-stream" : file.getContentType();
        if (!mime.matches("[A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+-]+")) mime = "application/octet-stream";
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        output.write(("--" + boundary + "\r\n").getBytes(StandardCharsets.UTF_8));
        output.write(("Content-Disposition: form-data; name=\"file\"; filename=\"" + filename + "\"\r\n").getBytes(StandardCharsets.UTF_8));
        output.write(("Content-Type: " + mime + "\r\n\r\n").getBytes(StandardCharsets.UTF_8));
        output.write(fileBytes);
        output.write(("\r\n--" + boundary + "--\r\n").getBytes(StandardCharsets.UTF_8));
        return output.toByteArray();
    }

    private static String multipartBoundary(String key, byte[] fileBytes) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            digest.update(key.getBytes(StandardCharsets.UTF_8));
            digest.update((byte) ':');
            digest.update(MessageDigest.getInstance("SHA-256").digest(fileBytes));
            String boundary = "DATA_AI_" + HexFormat.of().formatHex(digest.digest()).substring(0, 40);
            if (new String(fileBytes, StandardCharsets.ISO_8859_1).contains(boundary)) {
                throw new IllegalArgumentException("Multipart boundary collision; create a new command key");
            }
            return boundary;
        } catch (Exception ex) {
            throw new IllegalStateException("Cannot construct stable multipart boundary", ex);
        }
    }
}
