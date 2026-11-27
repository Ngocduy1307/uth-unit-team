package vn.unit.affordability.dossier.model;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import jakarta.persistence.UniqueConstraint;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;
import org.hibernate.annotations.CreationTimestamp;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;

import java.math.BigDecimal;
import java.time.OffsetDateTime;

@Entity
@Table(
    name = "evidence_ocr_results",
    uniqueConstraints = {
        @UniqueConstraint(
            name = "uq_evidence_ocr_version",
            columnNames = {"evidence_id", "ocr_version"}
        )
    }
)
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class EvidenceOcrResult {

    @Id
    @Column(name = "id", length = 36, nullable = false)
    private String id;

    @Column(name = "evidence_id", length = 36, nullable = false)
    private String evidenceId;

    @Column(name = "dossier_id", length = 36, nullable = false)
    private String dossierId;

    @Column(name = "ocr_version", nullable = false)
    @Builder.Default
    private Integer ocrVersion = 1;

    @Column(name = "engine_name", length = 64, nullable = false)
    private String engineName;

    @Column(name = "engine_version", length = 32)
    private String engineVersion;

    @Column(name = "confidence_score", precision = 5, scale = 2)
    private BigDecimal confidenceScore;

    @JdbcTypeCode(SqlTypes.JSON)
    @Column(name = "raw_payload", columnDefinition = "jsonb", nullable = false)
    private String rawPayload;

    @JdbcTypeCode(SqlTypes.JSON)
    @Column(name = "extracted_summary", columnDefinition = "jsonb")
    private String extractedSummary;

    @Column(name = "status", length = 32, nullable = false)
    @Builder.Default
    private String status = "COMPLETED";

    @Column(name = "error_message", columnDefinition = "TEXT")
    private String errorMessage;

    @Column(name = "processed_by", length = 64, nullable = false)
    private String processedBy;

    @Column(name = "processed_at", nullable = false)
    private OffsetDateTime processedAt;

    @CreationTimestamp
    @Column(name = "created_at", nullable = false, updatable = false)
    private OffsetDateTime createdAt;
}
