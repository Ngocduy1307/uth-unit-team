package vn.unit.affordability.dossier.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.math.BigDecimal;
import java.time.OffsetDateTime;

@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
@JsonInclude(JsonInclude.Include.NON_NULL)
public class EvidenceOcrResultResponse {

    private String id;
    private String evidenceId;
    private String dossierId;
    private Integer ocrVersion;
    private String engineName;
    private String engineVersion;
    private BigDecimal confidenceScore;
    private String rawPayload;
    private String extractedSummary;
    private String status;
    private String errorMessage;
    private String processedBy;
    private OffsetDateTime processedAt;
    private OffsetDateTime createdAt;
}
