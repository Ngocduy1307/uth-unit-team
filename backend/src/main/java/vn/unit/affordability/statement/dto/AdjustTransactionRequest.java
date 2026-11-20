package vn.unit.affordability.statement.dto;

import jakarta.validation.constraints.DecimalMin;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
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
public class AdjustTransactionRequest {

    @NotNull
    @DecimalMin(value = "0")
    private BigDecimal adjustedAmount;

    @NotBlank
    @Size(max = 64)
    private String adjustedBy;

    @NotBlank
    @Size(max = 1000)
    private String adjustmentReason;

    @NotNull
    private Boolean isAccepted;

    @Size(max = 255)
    private String exclusionReason;
}
