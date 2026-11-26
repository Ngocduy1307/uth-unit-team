package com.example.integration;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import java.nio.charset.StandardCharsets;
import java.security.SecureRandom;
import java.util.HexFormat;
import java.util.Base64;

/** Must sign the final serialized HTTP body, not the DTO before serialization. */
public final class DataAiAssertionSigner {
    private static final SecureRandom RANDOM = new SecureRandom();
    private DataAiAssertionSigner() {}

    public static String sign(String keyId, String secret, String issuer, String audience,
                              String method, String rawPath, String rawQuery, byte[] body,
                              String actorId, String actorRoles, String bankId) {
        return sign(keyId, secret, issuer, audience, method, rawPath, rawQuery, body,
            actorId, actorRoles, bankId, null);
    }

    /** V2 binds the optional Idempotency-Key into the HMAC canonical payload. */
    public static String sign(String keyId, String secret, String issuer, String audience,
                              String method, String rawPath, String rawQuery, byte[] body,
                              String actorId, String actorRoles, String bankId, String idempotencyKey) {
        if (secret == null || secret.getBytes(StandardCharsets.UTF_8).length < 32) {
            throw new IllegalArgumentException("DATA-AI signing key must contain at least 32 bytes");
        }
        byte[] nonceBytes = new byte[24];
        RANDOM.nextBytes(nonceBytes);
        String nonce = Base64.getUrlEncoder().withoutPadding().encodeToString(nonceBytes);
        String timestamp = Long.toString(System.currentTimeMillis() / 1000L);
        String bodyHash = sha256(body == null ? new byte[0] : body);
        String version = idempotencyKey == null ? "V1" : "V2";
        String canonical = String.join("\n",
            "DATA-AI-SERVICE-ASSERTION-" + version, issuer, audience, method.toUpperCase(), rawPath,
            rawQuery == null ? "" : rawQuery, bodyHash, timestamp, nonce,
            actorId, actorRoles == null ? "" : actorRoles, bankId);
        if (idempotencyKey != null) canonical += "\n" + idempotencyKey;
        String signature = hmacSha256(secret, canonical);
        return (idempotencyKey == null ? "v1." : "v2.") + keyId + "." + timestamp + "." + nonce + "." + signature;
    }

    private static String sha256(byte[] value) {
        try {
            return HexFormat.of().formatHex(java.security.MessageDigest.getInstance("SHA-256").digest(value));
        } catch (Exception ex) { throw new IllegalStateException(ex); }
    }

    private static String hmacSha256(String secret, String value) {
        try {
            Mac mac = Mac.getInstance("HmacSHA256");
            mac.init(new SecretKeySpec(secret.getBytes(StandardCharsets.UTF_8), "HmacSHA256"));
            return HexFormat.of().formatHex(mac.doFinal(value.getBytes(StandardCharsets.UTF_8)));
        } catch (Exception ex) { throw new IllegalStateException(ex); }
    }
}
