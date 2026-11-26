package com.example.integration;

import org.springframework.http.HttpRequest;
import org.springframework.http.client.ClientHttpRequestExecution;
import org.springframework.http.client.ClientHttpRequestInterceptor;
import org.springframework.http.client.ClientHttpResponse;
import java.io.IOException;

/** Adds a request-bound signature after Spring has serialized JSON/multipart bytes. */
public final class DataAiSignedAssertionInterceptor implements ClientHttpRequestInterceptor {
    private final String keyId;
    private final String secret;
    private final String issuer;
    private final String audience;
    public DataAiSignedAssertionInterceptor(String keyId, String secret, String issuer, String audience) {
        this.keyId = keyId;
        this.secret = secret;
        this.issuer = issuer;
        this.audience = audience;
    }

    @Override
    public ClientHttpResponse intercept(HttpRequest request, byte[] body,
                                        ClientHttpRequestExecution execution) throws IOException {
        var headers = request.getHeaders();
        String actor = required(headers.getFirst("X-Actor-Id"), "X-Actor-Id");
        String roles = headers.getFirst("X-Actor-Roles");
        String bank = required(headers.getFirst("X-Bank-Id"), "X-Bank-Id");
        var uri = request.getURI();
        String assertion = DataAiAssertionSigner.sign(
            keyId, secret, issuer, audience, request.getMethod().name(), uri.getRawPath(),
            uri.getRawQuery(), body, actor, roles, bank, headers.getFirst("Idempotency-Key"));
        headers.set("X-Service-Assertion", assertion);
        return execution.execute(request, body);
    }

    private static String required(String value, String name) {
        if (value == null || value.isBlank()) throw new IllegalStateException("Missing " + name);
        return value;
    }
}
