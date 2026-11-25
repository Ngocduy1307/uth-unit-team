package vn.unit.affordability.dossier.dto;

import jakarta.validation.constraints.DecimalMax;
import jakarta.validation.constraints.DecimalMin;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.math.BigDecimal;

@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class SubmitOcrResultRequest {

    @NotBlank
    @Size(max = 64)
    private String engineName;

    @Size(max = 32)
    private String engineVersion;

    @DecimalMin("0.00")
    @DecimalMax("100.00")
    private BigDecimal confidenceScore;

    @NotBlank
    private String rawPayload;

    private String extractedSummary;

    @NotBlank
    @Pattern(regexp = "^(COMPLETED|FAILED)$", message = "status must be COMPLETED or FAILED")
    private String status;

    @Size(max = 2000)
    private String errorMessage;

    @NotBlank
    @Size(max = 64)
    private String processedBy;
}
