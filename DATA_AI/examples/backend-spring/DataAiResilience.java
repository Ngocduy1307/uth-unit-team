package com.example.integration;

import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestClientResponseException;

import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ThreadLocalRandom;
import java.util.function.Supplier;

/**
 * Small process-local retry/circuit-breaker adapter for DATA-AI calls.
 * Mutation calls must supply the same persisted Idempotency-Key on each retry.
 */
public final class DataAiResilience {
    private static final int MAX_ATTEMPTS = 3;
    private static final int FAILURE_THRESHOLD = 5;
    private static final long OPEN_MILLIS = 30_000L;
    private static final ConcurrentHashMap<String, Circuit> CIRCUITS = new ConcurrentHashMap<>();

    private DataAiResilience() {}

    public static <T> T execute(String serviceKey, Supplier<T> operation) {
        Circuit circuit = CIRCUITS.computeIfAbsent(serviceKey, ignored -> new Circuit());
        circuit.acquire();
        RuntimeException last = null;
        for (int attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
            try {
                T result = operation.get();
                circuit.success();
                return result;
            } catch (RuntimeException ex) {
                if (!isRetryable(ex)) {
                    // A deterministic 4xx/business response is not service-health failure.
                    circuit.success();
                    throw ex;
                }
                last = ex;
                if (attempt == MAX_ATTEMPTS) break;
                long base = 150L << (attempt - 1);
                long delay = retryAfterMillis(ex, base) + ThreadLocalRandom.current().nextLong(0, 75);
                try {
                    Thread.sleep(delay);
                } catch (InterruptedException interrupted) {
                    Thread.currentThread().interrupt();
                    circuit.failure(); // Release a half-open probe if this call was interrupted.
                    throw new IllegalStateException("Interrupted while retrying DATA-AI", interrupted);
                }
            }
        }
        circuit.failure();
        throw last == null ? new IllegalStateException("DATA-AI request failed") : last;
    }

    private static boolean isRetryable(RuntimeException ex) {
        if (ex instanceof ResourceAccessException) return true;
        if (ex instanceof RestClientResponseException response) {
            int status = response.getStatusCode().value();
            String body = response.getResponseBodyAsString();
            if (status == 409) return body.contains("IDEMPOTENCY_IN_PROGRESS");
            if (status == 503) return body.contains("IDEMPOTENCY_STORE_UNAVAILABLE");
            return status == 429 || status == 502 || status == 504;
        }
        return false;
    }

    private static long retryAfterMillis(RuntimeException ex, long fallback) {
        if (ex instanceof RestClientResponseException response) {
            String value = response.getResponseHeaders() == null ? null
                : response.getResponseHeaders().getFirst("Retry-After");
            if (value != null) {
                try { return Math.min(5_000L, Math.max(0L, Long.parseLong(value) * 1000L)); }
                catch (NumberFormatException ignored) { /* use bounded exponential fallback */ }
            }
        }
        return fallback;
    }

    private static final class Circuit {
        private int consecutiveFailures;
        private long openedUntilMillis;
        private boolean halfOpenProbeInFlight;

        synchronized void acquire() {
            long now = System.currentTimeMillis();
            if (openedUntilMillis == 0L) return;
            if (now < openedUntilMillis) {
                throw new CircuitOpenException("DATA-AI circuit is open; retry after cooldown");
            }
            if (halfOpenProbeInFlight) {
                throw new CircuitOpenException("DATA-AI circuit is waiting for its half-open probe");
            }
            halfOpenProbeInFlight = true;
        }

        synchronized void success() {
            consecutiveFailures = 0;
            openedUntilMillis = 0L;
            halfOpenProbeInFlight = false;
        }

        synchronized void failure() {
            halfOpenProbeInFlight = false;
            consecutiveFailures++;
            if (consecutiveFailures >= FAILURE_THRESHOLD || openedUntilMillis != 0L) {
                openedUntilMillis = System.currentTimeMillis() + OPEN_MILLIS;
            }
        }
    }

    public static final class CircuitOpenException extends RuntimeException {
        public CircuitOpenException(String message) { super(message); }
    }
}
